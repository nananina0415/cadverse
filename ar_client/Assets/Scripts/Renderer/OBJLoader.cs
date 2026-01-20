using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace CADverse.Renderer
{
    /// <summary>
    /// 런타임에 OBJ 파일을 로드하여 Unity Mesh로 변환
    /// </summary>
    public static class OBJLoader
    {
        /// <summary>
        /// OBJ 텍스트 데이터를 파싱하여 Mesh 생성
        /// </summary>
        /// <param name="objData">OBJ 파일 내용 (텍스트)</param>
        /// <returns>생성된 Mesh</returns>
        public static Mesh LoadFromString(string objData)
        {
            var vertices = new List<Vector3>();
            var normals = new List<Vector3>();
            var uvs = new List<Vector2>();
            var triangles = new List<int>();

            var vertexIndices = new Dictionary<string, int>();
            var finalVertices = new List<Vector3>();
            var finalNormals = new List<Vector3>();
            var finalUVs = new List<Vector2>();

            var lines = objData.Split('\n');
            foreach (var line in lines)
            {
                var trimmed = line.Trim();
                if (string.IsNullOrEmpty(trimmed) || trimmed.StartsWith("#"))
                {
                    continue;
                }

                var parts = trimmed.Split(new[] { ' ' }, System.StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length == 0)
                {
                    continue;
                }

                switch (parts[0])
                {
                    case "v": // Vertex position
                        if (parts.Length >= 4)
                        {
                            vertices.Add(new Vector3(
                                ParseFloat(parts[1]),
                                ParseFloat(parts[2]),
                                ParseFloat(parts[3])
                            ));
                        }
                        break;

                    case "vn": // Vertex normal
                        if (parts.Length >= 4)
                        {
                            normals.Add(new Vector3(
                                ParseFloat(parts[1]),
                                ParseFloat(parts[2]),
                                ParseFloat(parts[3])
                            ));
                        }
                        break;

                    case "vt": // Texture coordinate
                        if (parts.Length >= 3)
                        {
                            uvs.Add(new Vector2(
                                ParseFloat(parts[1]),
                                ParseFloat(parts[2])
                            ));
                        }
                        break;

                    case "f": // Face
                        if (parts.Length >= 4)
                        {
                            // Triangle fan for polygons with more than 3 vertices
                            int firstIndex = ProcessVertex(parts[1], vertices, normals, uvs,
                                vertexIndices, finalVertices, finalNormals, finalUVs);

                            for (int i = 2; i < parts.Length - 1; i++)
                            {
                                int secondIndex = ProcessVertex(parts[i], vertices, normals, uvs,
                                    vertexIndices, finalVertices, finalNormals, finalUVs);
                                int thirdIndex = ProcessVertex(parts[i + 1], vertices, normals, uvs,
                                    vertexIndices, finalVertices, finalNormals, finalUVs);

                                triangles.Add(firstIndex);
                                triangles.Add(secondIndex);
                                triangles.Add(thirdIndex);
                            }
                        }
                        break;
                }
            }

            // Create mesh
            var mesh = new Mesh
            {
                vertices = finalVertices.ToArray(),
                triangles = triangles.ToArray()
            };

            if (finalNormals.Count == finalVertices.Count)
            {
                mesh.normals = finalNormals.ToArray();
            }
            else
            {
                mesh.RecalculateNormals();
            }

            if (finalUVs.Count == finalVertices.Count)
            {
                mesh.uv = finalUVs.ToArray();
            }

            mesh.RecalculateBounds();

            Debug.Log($"[OBJLoader] Loaded mesh: {finalVertices.Count} vertices, {triangles.Count / 3} triangles");

            return mesh;
        }

        private static int ProcessVertex(string vertexString,
            List<Vector3> vertices, List<Vector3> normals, List<Vector2> uvs,
            Dictionary<string, int> vertexIndices,
            List<Vector3> finalVertices, List<Vector3> finalNormals, List<Vector2> finalUVs)
        {
            // Check if we've already processed this vertex
            if (vertexIndices.TryGetValue(vertexString, out int existingIndex))
            {
                return existingIndex;
            }

            // Parse vertex reference: v/vt/vn or v//vn or v/vt or v
            var indices = vertexString.Split('/');
            int vIndex = int.Parse(indices[0]) - 1; // OBJ indices start at 1

            // Add vertex
            finalVertices.Add(vertices[vIndex]);

            // Add UV if available
            if (indices.Length > 1 && !string.IsNullOrEmpty(indices[1]))
            {
                int vtIndex = int.Parse(indices[1]) - 1;
                if (vtIndex >= 0 && vtIndex < uvs.Count)
                {
                    finalUVs.Add(uvs[vtIndex]);
                }
                else
                {
                    finalUVs.Add(Vector2.zero);
                }
            }
            else
            {
                finalUVs.Add(Vector2.zero);
            }

            // Add normal if available
            if (indices.Length > 2 && !string.IsNullOrEmpty(indices[2]))
            {
                int vnIndex = int.Parse(indices[2]) - 1;
                if (vnIndex >= 0 && vnIndex < normals.Count)
                {
                    finalNormals.Add(normals[vnIndex]);
                }
                else
                {
                    finalNormals.Add(Vector3.up);
                }
            }
            else
            {
                finalNormals.Add(Vector3.up);
            }

            int newIndex = finalVertices.Count - 1;
            vertexIndices[vertexString] = newIndex;

            return newIndex;
        }

        private static float ParseFloat(string str)
        {
            return float.Parse(str, CultureInfo.InvariantCulture);
        }
    }
}
