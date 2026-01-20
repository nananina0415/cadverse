using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.Text;
using Newtonsoft.Json.Linq;

namespace InterfaceCodeGen
{
    [Generator]
    public class TypeScriptInterfaceGenerator : ISourceGenerator
    {
        public void Initialize(GeneratorInitializationContext context)
        {
            // 초기화 로직 (필요 시)
        }

        public void Execute(GeneratorExecutionContext context)
        {
            try
            {
                // AdditionalFiles에서 TypeScript 파일 찾기
                var tsFile = context.AdditionalFiles
                    .FirstOrDefault(f => f.Path.EndsWith("touch_raycast_input.ts"));

                if (tsFile == null)
                {
                    return;
                }

                // 타입 매핑 파일 찾기 (client.json)
                var mappingFile = context.AdditionalFiles
                    .FirstOrDefault(f => f.Path.EndsWith("client.json"));

                Dictionary<string, string> typeMap = new Dictionary<string, string>
                {
                    { "number", "float" },
                    { "string", "string" },
                    { "boolean", "bool" },
                    { "Vector3", "Vector3" }
                };

                HashSet<string> skipInterfaces = new HashSet<string>();

                if (mappingFile != null)
                {
                    var mappingText = mappingFile.GetText(context.CancellationToken)?.ToString();
                    if (!string.IsNullOrEmpty(mappingText))
                    {
                        var mappingJson = JObject.Parse(mappingText);
                        var typeMappings = mappingJson["type_mappings"];
                        if (typeMappings != null)
                        {
                            typeMap = typeMappings.ToObject<Dictionary<string, string>>();
                        }

                        var skipList = mappingJson["skip_interfaces"];
                        if (skipList != null && skipList.Type == JTokenType.Array)
                        {
                            skipInterfaces = skipList.ToObject<HashSet<string>>();
                        }
                    }
                }

                // TypeScript 파일 내용 읽기
                var tsContent = tsFile.GetText(context.CancellationToken)?.ToString();
                if (string.IsNullOrEmpty(tsContent))
                {
                    return;
                }

                // TypeScript 인터페이스 파싱
                var interfaces = ParseTypeScriptInterfaces(tsContent);

                // skip_interfaces에 있는 인터페이스 제거
                foreach (var skipName in skipInterfaces)
                {
                    interfaces.Remove(skipName);
                }

                // C# 코드 생성
                var csCode = GenerateCSharpCode(interfaces, typeMap);

                // 생성된 코드를 컴파일에 추가
                context.AddSource("TouchRaycastMessage.g.cs", SourceText.From(csCode, Encoding.UTF8));
            }
            catch (Exception ex)
            {
                // Source Generator에서 예외 발생 시 진단 메시지 추가
                var descriptor = new DiagnosticDescriptor(
                    "TSGEN001",
                    "TypeScript Interface Generator Error",
                    $"Error generating code: {ex.Message}",
                    "CodeGen",
                    DiagnosticSeverity.Error,
                    isEnabledByDefault: true);

                context.ReportDiagnostic(Diagnostic.Create(descriptor, Location.None));
            }
        }

        private Dictionary<string, List<(string Name, string Type)>> ParseTypeScriptInterfaces(string tsContent)
        {
            var interfaces = new Dictionary<string, List<(string, string)>>();

            // interface 블록 매칭: interface Name { ... }
            var pattern = @"interface\s+(\w+)\s*\{([^}]+)\}";
            var matches = Regex.Matches(tsContent, pattern, RegexOptions.Multiline);

            foreach (Match match in matches)
            {
                var interfaceName = match.Groups[1].Value;
                var body = match.Groups[2].Value;

                var fields = new List<(string, string)>();

                // 필드 매칭: fieldName: type;
                var fieldPattern = @"\s*(\w+):\s*([^;]+);";
                var fieldMatches = Regex.Matches(body, fieldPattern);

                foreach (Match fieldMatch in fieldMatches)
                {
                    var fieldName = fieldMatch.Groups[1].Value;
                    var fieldType = fieldMatch.Groups[2].Value.Trim();

                    if (!string.IsNullOrEmpty(fieldName) && !string.IsNullOrEmpty(fieldType))
                    {
                        fields.Add((fieldName, fieldType));
                    }
                }

                if (fields.Count > 0)
                {
                    interfaces[interfaceName] = fields;
                }
            }

            return interfaces;
        }

        private string GenerateCSharpCode(
            Dictionary<string, List<(string Name, string Type)>> interfaces,
            Dictionary<string, string> typeMap)
        {
            var sb = new StringBuilder();

            sb.AppendLine("// AUTO-GENERATED CODE - DO NOT EDIT MANUALLY");
            sb.AppendLine("// Generated from: interface/touch_raycast_input.ts");
            sb.AppendLine("// Source Generator: InterfaceCodeGen");
            sb.AppendLine();
            sb.AppendLine("using UnityEngine;");
            sb.AppendLine();
            sb.AppendLine("namespace CADverse.Input");
            sb.AppendLine("{");

            foreach (var kvp in interfaces)
            {
                var interfaceName = kvp.Key;
                var fields = kvp.Value;

                sb.AppendLine();
                sb.AppendLine("    [System.Serializable]");
                sb.AppendLine($"    public class {interfaceName}");
                sb.AppendLine("    {");

                foreach (var (fieldName, fieldType) in fields)
                {
                    var csType = ConvertType(fieldType, typeMap);

                    // 리터럴 타입 처리 (e.g., type: "TouchStart")
                    if (fieldType.StartsWith("\"") && fieldType.EndsWith("\""))
                    {
                        var literalValue = fieldType.Trim('"');
                        sb.AppendLine($"        public {csType} {fieldName} = \"{literalValue}\";");
                    }
                    else
                    {
                        sb.AppendLine($"        public {csType} {fieldName};");
                    }
                }

                sb.AppendLine("    }");
            }

            sb.AppendLine("}");

            return sb.ToString();
        }

        private string ConvertType(string tsType, Dictionary<string, string> typeMap)
        {
            // 리터럴 타입 처리
            if (tsType.StartsWith("\"") && tsType.EndsWith("\""))
            {
                return "string";
            }

            // 매핑 테이블에서 찾기
            if (typeMap.TryGetValue(tsType, out var csType))
            {
                return csType;
            }

            // 매핑되지 않은 타입은 그대로 반환 (커스텀 타입으로 간주)
            return tsType;
        }
    }
}
