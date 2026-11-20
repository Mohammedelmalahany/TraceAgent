from traceagent.preprocessing.gold_labels import collect_scopes, extract_gold
from traceagent.preprocessing.patch_parser import apply_patch_to_text, parse_patch

OLD = '''\
import os


def helper(x):
    return x + 1


class Parser:
    mode = "a"

    @staticmethod
    def parse(text):
        def inner():
            return 1
        return text.strip()

    def run(self):
        return 0
'''

# Edits: helper body changed; class attribute changed; nested inner() changed (-> Parser.parse);
# a brand-new method Parser.extra added; a module-level import added.
PATCH = '''\
diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,5 +1,6 @@
 import os
+import sys


 def helper(x):
-    return x + 1
+    return x + 2
@@ -8,11 +9,14 @@ def helper(x):
 class Parser:
-    mode = "a"
+    mode = "b"

     @staticmethod
     def parse(text):
         def inner():
-            return 1
+            return 2
         return text.strip()

+    def extra(self):
+        return 1
+
     def run(self):
         return 0
'''


def test_parse_patch_line_numbers() -> None:
    [fp] = parse_patch(PATCH)
    assert fp.path == "pkg/mod.py"
    removed = [ln.old_lineno for h in fp.hunks for ln in h.lines if ln.tag == "-"]
    assert removed == [5, 9, 14]


def test_apply_patch_rebuilds_new_file() -> None:
    [fp] = parse_patch(PATCH)
    new = apply_patch_to_text(OLD, fp)
    assert "import sys" in new and "def extra(self):" in new and 'mode = "b"' in new
    assert 'mode = "a"' not in new


def test_nested_function_is_folded_and_decorator_included() -> None:
    scopes = {s.qualname: s for s in collect_scopes(OLD)}
    assert "Parser.parse.inner" not in scopes
    assert scopes["Parser.parse"].start == 11  # the @staticmethod line


def test_extract_gold_categories() -> None:
    gold = extract_gold(PATCH, lambda path: OLD)
    assert gold["files"] == ["pkg/mod.py"]
    assert gold["functions"] == ["pkg/mod.py::Parser.parse", "pkg/mod.py::helper"]
    assert gold["added_functions"] == ["pkg/mod.py::Parser.extra"]
    assert gold["edited_classes"] == ["pkg/mod.py::Parser"]
    assert gold["module_level_files"] == ["pkg/mod.py"]


def test_added_class_is_not_an_edited_class() -> None:
    # like matplotlib-24265: the patch adds `class _StyleLibrary(dict):`
    old = "def use(x):\n    return x\n"
    patch = ("--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,8 @@\n+class Lib(dict):\n+    kind = 1\n+\n+    def get(self):\n"
             "+        return 1\n+\n def use(x):\n-    return x\n+    return Lib()\n")
    gold = extract_gold(patch, lambda p: old)
    assert gold["edited_classes"] == []
    assert gold["added_classes"] == ["m.py::Lib"]
    assert gold["added_functions"] == ["m.py::Lib.get"]
    assert gold["functions"] == ["m.py::use"]


def test_form_feed_does_not_shift_line_numbers() -> None:
    # A form feed (\x0c) inside a line: str.splitlines() would split there, ast does not.
    old = "def a():\n    s = 'x\x0cy'\n    return s\n\n\ndef b():\n    return 1\n"
    patch = "--- a/m.py\n+++ b/m.py\n@@ -7,1 +7,1 @@\n-    return 1\n+    return 2\n"
    gold = extract_gold(patch, lambda p: old)
    assert gold["functions"] == ["m.py::b"]


def test_wrong_hunk_line_numbers_are_relocated_by_context() -> None:
    # Header claims line 2, but the context really sits at lines 6-7 (like sympy-14317).
    old = "x = 1\ny = 2\n\n\ndef a():\n    return 1\n\n\ndef b():\n    v = 0\n    return v\n"
    patch = "--- a/m.py\n+++ b/m.py\n@@ -6,2 +6,2 @@\n def b():\n-    v = 0\n+    v = 9\n"
    gold = extract_gold(patch, lambda p: old)
    assert gold["functions"] == ["m.py::b"]
    assert gold["offset_hunks"] == 1 and gold["unmatched_hunks"] == 0


def test_new_file_and_sql_comment_line() -> None:
    patch = '''\
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
 def f():
---    return 1
+    return 2
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+x = 1
'''
    old = "def f():\n--    return 1\n"  # not valid python, but parser must not split here
    files = parse_patch(patch)
    assert [f.path for f in files] == ["a.py", "new.py"]
    assert files[1].is_new_file
    assert [ln.tag for ln in files[0].hunks[0].lines] == [" ", "-", "+"]
    gold = extract_gold(patch, lambda p: old)
    assert gold["added_files"] == ["new.py"]
