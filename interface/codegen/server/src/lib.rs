use proc_macro::TokenStream;
use quote::quote;
use std::collections::HashMap;
use std::fs;
use std::path::Path;

/// TypeScript 인터페이스에서 Rust 구조체를 자동 생성하는 매크로
///
/// # 사용법
/// ```rust
/// use interface_codegen_macro::generate_from_typescript;
///
/// generate_from_typescript!("touch_raycast_input.ts");
/// ```
#[proc_macro]
pub fn generate_from_typescript(input: TokenStream) -> TokenStream {
    let input_str = input.to_string();
    let ts_filename = input_str.trim_matches('"');

    // interface 폴더의 TypeScript 파일 경로 찾기
    let interface_dir = find_interface_dir();
    let ts_path = interface_dir.join(ts_filename);

    if !ts_path.exists() {
        panic!("TypeScript file not found: {:?}", ts_path);
    }

    // type_mapping/server.json 읽기
    let mapping_path = interface_dir.join("type_mapping").join("server.json");
    let type_map = if mapping_path.exists() {
        load_type_mappings(&mapping_path)
    } else {
        get_default_type_map()
    };

    // TypeScript 파일 파싱
    let ts_content = fs::read_to_string(&ts_path)
        .unwrap_or_else(|e| panic!("Failed to read {:?}: {}", ts_path, e));

    let interfaces = parse_typescript_interfaces(&ts_content);

    // Rust 코드 생성
    let rust_code = generate_rust_structs(&interfaces, &type_map);

    rust_code.into()
}

fn find_interface_dir() -> std::path::PathBuf {
    // 현재 작업 디렉토리에서 interface 폴더 찾기
    let current = std::env::current_dir().unwrap();

    // 상위 디렉토리로 올라가면서 interface 폴더 찾기
    let mut path = current.clone();
    for _ in 0..5 {
        let interface_path = path.join("interface");
        if interface_path.exists() {
            return interface_path;
        }
        if !path.pop() {
            break;
        }
    }

    panic!("interface directory not found from {:?}", current);
}

fn load_type_mappings(path: &Path) -> HashMap<String, String> {
    let content = fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("Failed to read type mappings: {}", e));

    let json: serde_json::Value = serde_json::from_str(&content)
        .unwrap_or_else(|e| panic!("Failed to parse type mappings JSON: {}", e));

    if let Some(mappings) = json.get("type_mappings") {
        serde_json::from_value(mappings.clone()).unwrap_or_else(|_| get_default_type_map())
    } else {
        get_default_type_map()
    }
}

fn get_default_type_map() -> HashMap<String, String> {
    let mut map = HashMap::new();
    map.insert("number".to_string(), "f32".to_string());
    map.insert("string".to_string(), "String".to_string());
    map.insert("boolean".to_string(), "bool".to_string());
    map
}

#[derive(Debug)]
struct InterfaceField {
    name: String,
    ts_type: String,
}

fn parse_typescript_interfaces(content: &str) -> HashMap<String, Vec<InterfaceField>> {
    use regex::Regex;

    let mut interfaces = HashMap::new();

    // interface 블록 매칭
    let interface_regex = Regex::new(r"interface\s+(\w+)\s*\{([^}]+)\}").unwrap();

    for cap in interface_regex.captures_iter(content) {
        let name = cap[1].to_string();
        let body = &cap[2];

        let mut fields = Vec::new();

        // 필드 매칭: fieldName: type;
        let field_regex = Regex::new(r"\s*(\w+):\s*([^;]+);").unwrap();

        for field_cap in field_regex.captures_iter(body) {
            let field_name = field_cap[1].trim().to_string();
            let field_type = field_cap[2].trim().to_string();

            if !field_name.is_empty() && !field_type.is_empty() {
                fields.push(InterfaceField {
                    name: field_name,
                    ts_type: field_type,
                });
            }
        }

        // 빈 인터페이스도 포함 (TouchEndPayload 등)
        interfaces.insert(name, fields);
    }

    interfaces
}

fn convert_type(ts_type: &str, type_map: &HashMap<String, String>) -> String {
    // 리터럴 타입 처리 (e.g., "TouchStart")
    if ts_type.starts_with('"') && ts_type.ends_with('"') {
        return "String".to_string();
    }

    // 타입 매핑 테이블에서 찾기
    type_map.get(ts_type)
        .cloned()
        .unwrap_or_else(|| ts_type.to_string())
}

fn camel_to_snake_case(s: &str) -> String {
    let mut result = String::new();
    for (i, ch) in s.chars().enumerate() {
        if ch.is_uppercase() {
            if i > 0 {
                result.push('_');
            }
            result.push(ch.to_lowercase().next().unwrap());
        } else {
            result.push(ch);
        }
    }
    result
}

fn is_rust_keyword(name: &str) -> bool {
    matches!(
        name,
        "as" | "break" | "const" | "continue" | "crate" | "else" | "enum" | "extern"
            | "false" | "fn" | "for" | "if" | "impl" | "in" | "let" | "loop" | "match"
            | "mod" | "move" | "mut" | "pub" | "ref" | "return" | "self" | "Self"
            | "static" | "struct" | "super" | "trait" | "true" | "type" | "unsafe"
            | "use" | "where" | "while" | "async" | "await" | "dyn" | "abstract"
            | "become" | "box" | "do" | "final" | "macro" | "override" | "priv"
            | "typeof" | "unsized" | "virtual" | "yield" | "try"
    )
}

fn generate_rust_structs(
    interfaces: &HashMap<String, Vec<InterfaceField>>,
    type_map: &HashMap<String, String>,
) -> TokenStream {
    let mut struct_tokens = Vec::new();

    for (interface_name, fields) in interfaces {
        let struct_name = syn::Ident::new(interface_name, proc_macro2::Span::call_site());

        let field_tokens: Vec<_> = fields.iter().map(|field| {
            let field_name_snake = camel_to_snake_case(&field.name);

            // Rust 키워드인 경우 r# 접두사 추가
            let field_ident = if is_rust_keyword(&field_name_snake) {
                syn::Ident::new_raw(&field_name_snake, proc_macro2::Span::call_site())
            } else {
                syn::Ident::new(&field_name_snake, proc_macro2::Span::call_site())
            };

            let rust_type_str = convert_type(&field.ts_type, type_map);
            let rust_type: proc_macro2::TokenStream = rust_type_str.parse().unwrap();

            // 원본 필드명 (camelCase)
            let original_name = &field.name;

            // snake_case와 camelCase가 다른 경우 rename 추가
            if field_name_snake != *original_name {
                quote! {
                    #[serde(rename = #original_name)]
                    pub #field_ident: #rust_type
                }
            } else {
                quote! {
                    pub #field_ident: #rust_type
                }
            }
        }).collect();

        struct_tokens.push(quote! {
            #[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
            pub struct #struct_name {
                #(#field_tokens),*
            }
        });
    }

    let output = quote! {
        #(#struct_tokens)*
    };

    output.into()
}
