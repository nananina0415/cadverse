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
                        // OBJ는 밀리미터 단위 → 미터 단위로 변환
                        vertices.Add(new Vector3(x * 0.001f, y * 0.001f, z * 0.001f));
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
        /// 메쉬의 바운딩 박스 중심을 원점으로 이동시킨다.
        /// </summary>
        /// <param name="objText">OBJ 파일 내용</param>
        /// <param name="objectName">생성할 GameObject 이름 (기본값: "ObjModel")</param>
        /// <returns>MeshFilter와 MeshRenderer가 추가된 GameObject</returns>
        public static GameObject ParseToGameObject(string objText, string objectName = "ObjModel")
        {
            Mesh mesh = ParseToMesh(objText);

            // 바운딩 박스 정보 로그 (중심 이동은 ModelManager에서 전체 모델 기준으로 처리)
            Debug.Log($"[ObjCommunication] {objectName} 바운딩 박스 중심: {mesh.bounds.center * 1000}mm, 크기: {mesh.bounds.size * 1000}mm");

            GameObject obj = new GameObject(objectName);
            obj.AddComponent<MeshFilter>().mesh = mesh;

            // Material 생성 - 부품별 색상 적용
            Material material = CreateMaterial(objectName);
            obj.AddComponent<MeshRenderer>().material = material;

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

        // 부품별 색상표 (구분하기 쉬운 색상)
        private static readonly Color[] PartColors = new Color[]
        {
            new Color(0.3f, 0.5f, 0.8f),   // 파란색 (base)
            new Color(0.9f, 0.4f, 0.2f),   // 주황색 (shaft)
            new Color(0.2f, 0.7f, 0.3f),   // 초록색
            new Color(0.8f, 0.2f, 0.5f),   // 분홍색
            new Color(0.6f, 0.6f, 0.2f),   // 올리브
            new Color(0.5f, 0.3f, 0.7f),   // 보라색
        };
        private static int _colorIndex = 0;

        /// <summary>
        /// 부품별 Material을 생성한다.
        /// </summary>
        private static Material CreateMaterial(string objectName)
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null)
            {
                shader = Shader.Find("Universal Render Pipeline/Simple Lit");
            }
            if (shader == null)
            {
                shader = Shader.Find("Standard");
            }
            if (shader == null)
            {
                shader = Shader.Find("UI/Default");
            }

            if (shader == null)
            {
                throw new System.InvalidOperationException("[ObjCommunication] 사용 가능한 Shader를 찾을 수 없습니다!");
            }

            Material material = new Material(shader);

            // 부품 이름에 따른 색상 지정 또는 순차 색상
            Color partColor;
            if (objectName.ToLower().Contains("base"))
            {
                partColor = PartColors[0]; // 파란색
            }
            else if (objectName.ToLower().Contains("shaft"))
            {
                partColor = PartColors[1]; // 주황색
            }
            else
            {
                partColor = PartColors[_colorIndex % PartColors.Length];
                _colorIndex++;
            }

            // URP Lit/Simple Lit 또는 Standard에 색상 적용
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", partColor);
            }
            else if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", partColor);
            }
            else
            {
                material.color = partColor;
            }

            Debug.Log($"[ObjCommunication] {objectName} 색상: RGB({partColor.r:F2}, {partColor.g:F2}, {partColor.b:F2})");
            return material;
        }
    }
}
