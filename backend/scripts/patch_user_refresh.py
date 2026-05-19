# -*- coding: utf-8 -*-
import pathlib

p = pathlib.Path(__file__).resolve().parents[1] / "templates" / "admin.html"
t = p.read_text(encoding="utf-8")

if "bindUserTableEvents" not in t:
    insert = """
    function bindUserTableEvents() {
      var tbody = document.getElementById('userTable');
      if (!tbody || tbody._deleteBound) return;
      tbody._deleteBound = true;
      tbody.addEventListener('click', function(e) {
        var btn = e.target.closest('.btn-delete-user');
        if (btn && btn.dataset.uid) deleteUser(btn.dataset.uid);
      });
    }
"""
    t = t.replace("    function getSelectedUserIds() {", insert + "\n    function getSelectedUserIds() {")
    print("bind inserted")

old_btn = "        ops += '<button class=\"danger\" onclick=\"deleteUser('\\'' + uid + '\\')\">删除</button></motion.div>';"
old_btn = old_btn.replace("motion.div", "motion.div")
# find line containing deleteUser and 删除
lines = t.splitlines()
for i, line in enumerate(lines):
    if "deleteUser" in line and "删除" in line and "ops +=" in line:
        print("found line", i + 1, line[:100])
        lines[i] = "        ops += '<button type=\"button\" class=\"danger btn-delete-user\" data-uid=\"' + uid + '\">删除</button></div>';"
        t = "\n".join(lines)
        print("btn line replaced")
        break

if "bindUserTableEvents();" not in t:
    t = t.replace(
        "      updateUserSelectHint();\n    }",
        "      updateUserSelectHint();\n      bindUserTableEvents();\n    }",
        1,
    )
    print("bind call added")

p.write_text(t, encoding="utf-8")
print("done")
