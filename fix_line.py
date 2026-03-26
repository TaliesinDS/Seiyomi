with open("import_mangadex_bookmarks_to_suwayomi_refactored.py", "r", encoding="utf-8") as f:
    lines = f.readlines()
old = lines[2482]
new = '                logger.info(f"Raw status summary:' + "{'.'." + "join(f'{k}={v}' for k,v in sorted(raw_counts.items()))}" + '")\n'
lines[2482] = new
with open("import_mangadex_bookmarks_to_suwayomi_refactored.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("OLD:", repr(old))
print("NEW:", repr(new))
