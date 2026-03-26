lines = open('gui_launcher_tk.py', encoding='utf-8').readlines()
lines[1454] = (
    "    ab_desc = ttk.Label(about, "
    "text='Seiyomi (\u6574\u8aad\u307f, \"organize reading\") \u2014 "
    "import, migrate, and clean up your Suwayomi library. "
    "MangaDex import is one of several supported workflows.', "
    "wraplength=780, justify='left')\n"
)
open('gui_launcher_tk.py', 'w', encoding='utf-8').writelines(lines)
print('done')
