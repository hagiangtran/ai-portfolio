"""Capture PNG screenshots of Adobe Premiere CEP extension panels via headless Edge."""

from pathlib import Path
import re
import shutil
import tempfile

from playwright.sync_api import sync_playwright

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

SHOTS_DIR = Path(__file__).resolve().parent

PANELS = [
    {
        "html": Path(r"D:/Tool Pr/premiere-voice-cutter/client/index.html"),
        "output": SHOTS_DIR / "voice-cutter.png",
        "width": 440,
        "height": 640,
        "full_page": True,
    },
    {
        "html": Path(r"D:/Tool Pr/footage-replacer/client/index.html"),
        "output": SHOTS_DIR / "footage-replacer.png",
        "width": 520,
        "height": 460,
        "full_page": True,
    },
    {
        "html": Path(r"D:/Tool Pr/REPLACE ELEMENT V2/index.html"),
        "output": SHOTS_DIR / "auto-replace.png",
        "width": 430,
        "height": 480,
        "full_page": False,
    },
    {
        "html": Path(r"D:/Tool Pr/MyPremiereExtension/index.html"),
        "output": SHOTS_DIR / "align-distribute.png",
        "width": 420,
        "height": 410,
        "full_page": True,
    },
]


def find_edge() -> str:
    """Return path to Microsoft Edge executable."""
    for candidate in EDGE_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("msedge")
    if found:
        return found
    raise FileNotFoundError("Microsoft Edge (msedge.exe) not found.")


def find_extension_root(html_path: Path) -> Path:
    """Walk up from html_path to find the extension root containing CSXS/."""
    for parent in [html_path.parent, *html_path.parents]:
        if (parent / "CSXS").is_dir():
            return parent
    raise FileNotFoundError(f"Could not find CSXS folder above {html_path}")


def build_cep_stub(ext_root_posix: str) -> str:
    """Build <script> stub for window.__adobe_cep__ and minimal Node fallback."""
    safe_root = ext_root_posix.replace("\\", "/").replace('"', '\\"')
    return (
        "<script>\n"
        "(function() {\n"
        "  window.__adobe_cep__ = {\n"
        "    getHostEnvironment: function() {\n"
        "      return JSON.stringify({\n"
        '        appSkinInfo: { panelBackgroundColor: { color: { red: 35, green: 35, blue: 35 } } },\n'
        '        appName: "PPRO",\n'
        '        appVersion: "24.0",\n'
        '        appLocale: "en_US"\n'
        "      });\n"
        "    },\n"
        '    evalScript: function(s, cb) { if (cb) cb(""); },\n'
        f'    getSystemPath: function(type) {{ return type === "extension" ? "{safe_root}" : ""; }},\n'
        "    getScaleFactor: function() { return 1; },\n"
        "    getMonitorScaleFactor: function() { return 1; },\n"
        '    getExtensionId: function() { return "com.stub.extension"; },\n'
        '    getHostCapabilities: function() { return "{}"; },\n'
        '    getCurrentApiVersion: function() { return JSON.stringify({ major: 9, minor: 0, micro: 0 }); },\n'
        "    addEventListener: function() {},\n"
        "    removeEventListener: function() {},\n"
        "    dispatchEvent: function() {},\n"
        '    invokeSync: function() { return ""; },\n'
        '    invokeAsync: function(cmd, data, cb) { if (cb) cb(""); },\n'
        "    registerKeyEventsInterest: function() {},\n"
        "    resizeContent: function() {},\n"
        "    closeExtension: function() {}\n"
        "  };\n"
        '  if (typeof window.require === "undefined") {\n'
        "    window.require = function(mod) {\n"
        '      if (mod === "child_process") return { spawn: function() { return { stdout: { on: function() {} }, stderr: { on: function() {} }, on: function() {} }; } };\n'
        '      if (mod === "fs") return { existsSync: function() { return true; }, readFileSync: function() { return ""; }, mkdtempSync: function() { return ""; }, writeFileSync: function() {}, rmSync: function() {} };\n'
        '      if (mod === "path") return { resolve: function() { return ""; }, join: function() { return Array.prototype.slice.call(arguments).join("/"); }, basename: function(p) { return String(p || "").split(/[\\\\/]/).pop(); } };\n'
        '      if (mod === "os") return { tmpdir: function() { return ""; } };\n'
        "      return {};\n"
        "    };\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )


def inject_stub_into_head(html_path: Path, stub_script: str) -> None:
    """Insert stub_script as the first element inside <head>."""
    content = html_path.read_text(encoding="utf-8")
    pattern = re.compile(r"(<head\b[^>]*>)", re.IGNORECASE)
    if not pattern.search(content):
        raise ValueError(f"No <head> tag found in {html_path}")
    updated = pattern.sub(r"\1\n" + stub_script, content, count=1)
    html_path.write_text(updated, encoding="utf-8")


def capture_panel(browser, panel: dict) -> None:
    """Copy extension folder to temp, inject CEP stub, and screenshot via headless Edge."""
    src_html: Path = panel["html"]
    ext_root = find_extension_root(src_html)
    rel_html = src_html.relative_to(ext_root)

    tmp_dir = Path(tempfile.mkdtemp(prefix="cep_shot_"))
    try:
        copied_root = tmp_dir / ext_root.name
        shutil.copytree(ext_root, copied_root)

        copied_html = copied_root / rel_html
        inject_stub_into_head(copied_html, build_cep_stub(copied_root.as_posix()))

        out_path: Path = panel["output"]
        out_path.parent.mkdir(parents=True, exist_ok=True)

        context = browser.new_context(
            viewport={"width": panel["width"], "height": panel["height"]},
            device_scale_factor=2,
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        page.goto(copied_html.as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
        page.screenshot(path=str(out_path), full_page=panel["full_page"])
        context.close()

        if errors:
            raise RuntimeError(f"Page errors in {src_html}: {errors}")
        print(f"Captured {out_path.name} ({panel['width']}x{panel['height']} @2x, full_page={panel['full_page']})")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    edge_exe = find_edge()
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=edge_exe, headless=True)
        try:
            for panel in PANELS:
                capture_panel(browser, panel)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
