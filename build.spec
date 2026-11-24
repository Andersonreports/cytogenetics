# PyInstaller spec for the CMC Cytogenetics report tool - one executable.
# Build:  build.bat   or   python -m PyInstaller build.spec --noconfirm --clean
# The exe starts the local web server and opens the browser; its console window
# shows the address, and closing it stops the tool. PDFs need Word or LibreOffice
# on the user's PC.

a = Analysis(
    ["backend/main.py"],
    pathex=["."],
    # Only the blank template from assets/ (assets/WES report template/ holds patient
    # reports: never bundled). database/ = the OMIM tables, when present on this PC.
    datas=[("frontend", "frontend"), ("assets/cmc_cytogenetics.docx", "assets"),
           ("database", "database")],
    hiddenimports=["docx", "openpyxl", "pypdfium2", "PIL", "win32com.client", "pythoncom"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="CMCCytogeneticsReport",
    console=True,
    upx=False,
)
