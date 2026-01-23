using UnityEngine;
using UnityEditor;

namespace CADverse.Editor
{
    /// <summary>
    /// 셰이더 키워드 오류를 수정하는 에디터 유틸리티
    /// </summary>
    public class FixShaderKeywords
    {
        [MenuItem("CADverse/Fix Shader Keywords")]
        public static void FixAllMaterials()
        {
            // 모든 Material 찾기
            string[] guids = AssetDatabase.FindAssets("t:Material");
            int fixedCount = 0;
            int totalCount = guids.Length;

            Debug.Log($"[FixShaderKeywords] Found {totalCount} materials");

            foreach (string guid in guids)
            {
                string path = AssetDatabase.GUIDToAssetPath(guid);
                Material material = AssetDatabase.LoadAssetAtPath<Material>(path);

                if (material == null)
                    continue;

                // Shader 이름 확인
                if (material.shader != null)
                {
                    string shaderName = material.shader.name;

                    // "Simulation/Standard Lit" 또는 호환되지 않는 셰이더 찾기
                    // 혹은 Standard 셰이더도 URP로 변환
                    if (shaderName.Contains("Simulation") || shaderName.Contains("Standard Lit") || shaderName == "Standard")
                    {
                        Debug.Log($"[FixShaderKeywords] Fixing material: {path} (shader: {shaderName})");

                        // URP Lit 셰이더로 교체
                        Shader urpShader = Shader.Find("Universal Render Pipeline/Lit");
                        if (urpShader != null)
                        {
                            material.shader = urpShader;
                            EditorUtility.SetDirty(material);
                            fixedCount++;
                        }
                        else
                        {
                            Debug.LogError($"[FixShaderKeywords] URP Lit shader not found!");
                        }
                    }
                }
            }

            if (fixedCount > 0)
            {
                AssetDatabase.SaveAssets();
                AssetDatabase.Refresh();
                Debug.Log($"[FixShaderKeywords] Fixed {fixedCount} materials");
            }
            else
            {
                Debug.Log("[FixShaderKeywords] No materials needed fixing");
            }
        }
    }
}
