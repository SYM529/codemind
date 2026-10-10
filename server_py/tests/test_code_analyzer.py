from services.code_analyzer import analyze_code


def test_analyze_javascript_functions_classes_imports():
    code = "\n".join([
        "import helper from './helper';",
        "function add(a, b) { return a + b; }",
        "const multiply = (left, right) => left * right;",
        "class Calculator {}",
    ])
    structure = analyze_code(code, "javascript")
    names = {f["name"] for f in structure["functions"]}
    assert {"add", "multiply"} <= names
    assert structure["classes"][0]["name"] == "Calculator"
    assert structure["imports"][0]["line"] == 1


def test_analyze_javascript_reports_line_numbers():
    code = "const a = 1;\n\nfunction foo(x) { return x; }"
    structure = analyze_code(code, "javascript")
    foo = next(f for f in structure["functions"] if f["name"] == "foo")
    assert foo["line"] == 3
    assert foo["parameters"] == ["x"]


def test_analyze_python_functions_and_params():
    code = "def add(a, b):\n    return a + b\n\nclass Calc:\n    pass\n"
    structure = analyze_code(code, "python")
    assert structure["functions"][0]["name"] == "add"
    assert structure["functions"][0]["parameters"] == ["a", "b"]
    assert structure["classes"][0]["name"] == "Calc"


def test_analyze_java_class_methods_constructor_fields():
    code = "\n".join([
        "package com.demo;",
        "",
        "import java.util.List;",
        "",
        "public class UserService {",
        "    private static final int MAX = 100;",
        "",
        "    public UserService(String name) {",
        "        this.name = name;",
        "    }",
        "",
        "    @Override",
        "    public List<String> findUsers(int limit, String... keywords) throws RuntimeException {",
        "        return null;",
        "    }",
        "",
        "    static <T extends Comparable<T>> T max(T a, T b) {",
        "        return a;",
        "    }",
        "",
        "    private boolean isValid(String s) {",
        "        if (s != null) {",
        "            System.out.println(s);",
        "        }",
        "        return s != null;",
        "    }",
        "}",
    ])
    structure = analyze_code(code, "java")
    assert [c["name"] for c in structure["classes"]] == ["UserService"]
    names = {f["name"]: f for f in structure["functions"]}
    assert set(names) == {"UserService", "findUsers", "max", "isValid"}
    assert names["UserService"]["parameters"] == ["name"]
    assert names["findUsers"]["parameters"] == ["limit", "keywords"]
    assert names["max"]["parameters"] == ["a", "b"]
    field_names = {v["name"] for v in structure["variables"]}
    assert "MAX" in field_names
    assert structure["imports"][0]["line"] == 3
    # 方法体内的控制语句和方法调用不得被识别为方法
    assert "println" not in names
    assert "if" not in names
