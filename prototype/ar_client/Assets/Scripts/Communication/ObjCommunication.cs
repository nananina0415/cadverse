using System.Collections.Generic;
using UnityEngine;

namespace CADverse.Communication
{
    /// <summary>
    /// OBJ 파일 문자열을 파싱하여 Unity Mesh로 변환하는 헬퍼 클래스
    /// </summary>
    public static class ObjCommunication
    {
        /// <summary>
        /// OBJ 문자열을 파싱하여 Mesh를 생성한다.
        /// </summary>
        /// <param name="objText">OBJ 파일 내용</param>
        /// <returns>Unity Mesh</returns>
        public static Mesh ParseToMesh(string objText)
        {
            if (string.IsNullOrWhiteSpace(objText))
            {
                throw new System.ArgumentException("OBJ 텍스트가 비어 있습니다.", nameof(objText));
            }

            List<Vector3> vertices = new List<Vector3>();
            List<int> triangles = new List<int>();

            string[] lines = objText.Split('\n');

            foreach (string line in lines)
            {
                string trimmedLine = line.Trim();
                if (string.IsNullOrEmpty(trimmedLine))
                {
                    continue;
                }

                string[] parts = trimmedLine.Split(' ');
                if (parts.Length == 0)
                {
                    continue;
                }

                // 정점 좌표 (v x y z)
                if (parts[0] == "v" && parts.Length >= 4)
                {
                    if (float.TryParse(parts[1], out float x) &&
                        float.TryParse(parts[2], out float y) &&
                        float.TryParse(parts[3], out float z))
                    {
                        // OBJ는 Y-up, Unity도 Y-up이지만 Z축 방향이 반대일 수 있음
                        vertices.Add(new Vector3(x, y, z));
                    }
                }
                // 면 정보 (f v1 v2 v3 또는 f v1/vt1/vn1 v2/vt2/vn2 v3/vt3/vn3)
                else if (parts[0] == "f" && parts.Length >= 4)
                {
                    // 간단한 파싱: 슬래시로 구분된 첫 번째 숫자만 사용
                    if (TryParseVertexIndex(parts[1], out int v1) &&
                        TryParseVertexIndex(parts[2], out int v2) &&
                        TryParseVertexIndex(parts[3], out int v3))
                    {
                        // OBJ는 1부터 시작, Unity는 0부터
                        triangles.Add(v1 - 1);
                        triangles.Add(v2 - 1);
                        triangles.Add(v3 - 1);
                    }
                }
            }

            if (vertices.Count == 0)
            {
                throw new System.InvalidOperationException("OBJ 파일에서 정점을 찾을 수 없습니다.");
            }

            if (triangles.Count == 0)
            {
                throw new System.InvalidOperationException("OBJ 파일에서 면을 찾을 수 없습니다.");
            }

            // Mesh 생성
            Mesh mesh = new Mesh();
            mesh.vertices = vertices.ToArray();
            mesh.triangles = triangles.ToArray();
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();

            return mesh;
        }

        /// <summary>
        /// OBJ 문자열을 파싱하여 GameObject를 생성한다.
        /// </summary>
        /// <param name="objText">OBJ 파일 내용</param>
        /// <param name="objectName">생성할 GameObject 이름 (기본값: "ObjModel")</param>
        /// <returns>MeshFilter와 MeshRenderer가 추가된 GameObject</returns>
        public static GameObject ParseToGameObject(string objText, string objectName = "ObjModel")
        {
            Mesh mesh = ParseToMesh(objText);

            GameObject obj = new GameObject(objectName);
            obj.AddComponent<MeshFilter>().mesh = mesh;
            obj.AddComponent<MeshRenderer>().material = new Material(Shader.Find("Standard"));

            return obj;
        }

        private static bool TryParseVertexIndex(string vertexData, out int index)
        {
            index = 0;

            // "v1/vt1/vn1" 형식에서 v1만 추출
            string[] components = vertexData.Split('/');
            if (components.Length == 0)
            {
                return false;
            }

            return int.TryParse(components[0], out index);
        }
    }
}
