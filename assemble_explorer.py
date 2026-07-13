import os
HERE = os.path.dirname(os.path.abspath(__file__))
template = open(os.path.join(HERE, "explorer_template.html"), encoding="utf-8").read()
data = open(os.path.join(HERE, "viz_data.json"), encoding="utf-8").read()

assert "__VIZ_DATA__" in template, "placeholder missing"
# guard against a literal "</script" substring in any title breaking out of the <script> block
data_safe = data.replace("</script", "<\\/script")

out = template.replace("__VIZ_DATA__", data_safe)
out_path = os.path.join(HERE, "explorer.html")
open(out_path, "w", encoding="utf-8").write(out)
print("written", out_path, len(out), "bytes")
