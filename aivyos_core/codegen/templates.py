"""项目脚手架模板（文档 §10.2 / T5.3）：7 种真实可用骨架（纯 stdlib 生成）。

每个模板：generator(spec) -> dict[相对路径 -> 内容]
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

TemplateGen = Callable[[Any], Dict[str, str]]


def _static(spec) -> Dict[str, str]:
    title = spec.title
    return {
        "index.html": f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <h1>{title}</h1>
  <main id="app"></main>
  <script src="script.js"></script>
</body>
</html>
""",
        "style.css": "body { font-family: system-ui; margin: 2rem; color: #222; }\nh1 { color: #2563eb; }\n",
        "script.js": "// AivyOS 生成\nconsole.log('ready');\n",
    }


def _react(spec) -> Dict[str, str]:
    title = spec.title
    return {
        "package.json": json_dumps({
            "name": spec.target_dir, "private": True, "version": "0.1.0", "type": "module",
            "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
            "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
            "devDependencies": {"@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.0"},
        }),
        "vite.config.js": "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\nexport default defineConfig({ plugins: [react()] });\n",
        "index.html": f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\"/><title>{title}</title></head><body><div id=\"root\"></div><script type=\"module\" src=\"/src/main.jsx\"></script></body></html>\n",
        "src/main.jsx": "import React from 'react';\nimport ReactDOM from 'react-dom/client';\nimport App from './App.jsx';\nReactDOM.createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);\n",
        "src/App.jsx": f"export default function App() {{\n  return <div><h1>{title}</h1><p>React + Vite 骨架（AivyOS 生成）</p></div>;\n}}\n",
        "src/index.css": "body { font-family: system-ui; margin: 2rem; }\n",
    }


def _vue(spec) -> Dict[str, str]:
    title = spec.title
    return {
        "package.json": json_dumps({
            "name": spec.target_dir, "private": True, "version": "0.1.0", "type": "module",
            "scripts": {"dev": "vite", "build": "vite build"},
            "dependencies": {"vue": "^3.4.0"},
            "devDependencies": {"@vitejs/plugin-vue": "^5.0.0", "vite": "^5.4.0"},
        }),
        "vite.config.js": "import { defineConfig } from 'vite';\nimport vue from '@vitejs/plugin-vue';\nexport default defineConfig({ plugins: [vue()] });\n",
        "index.html": f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\"/><title>{title}</title></head><body><div id=\"app\"></div><script type=\"module\" src=\"/src/main.js\"></script></body></html>\n",
        "src/main.js": "import { createApp } from 'vue';\nimport App from './App.vue';\ncreateApp(App).mount('#app');\n",
        "src/App.vue": f"<template><div><h1>{title}</h1></div></template>\n<script setup></script>\n",
    }


def _nextjs(spec) -> Dict[str, str]:
    title = spec.title
    return {
        "package.json": json_dumps({
            "name": spec.target_dir, "private": True, "version": "0.1.0",
            "scripts": {"dev": "next dev", "build": "next build"},
            "dependencies": {"next": "^14.2.0", "react": "^18.3.1", "react-dom": "^18.3.1"},
        }),
        "pages/index.js": f"export default function Home() {{\n  return <div><h1>{title}</h1><p>Next.js 骨架（AivyOS 生成）</p></div>;\n}}\n",
        "pages/_app.js": "export default function App({ Component, pageProps }) { return <Component {...pageProps} />; }\n",
        "next.config.js": "module.exports = {};\n",
    }


def _python_cli(spec) -> Dict[str, str]:
    title = spec.title
    return {
        "main.py": f"""# {title} — AivyOS 生成 CLI 骨架
import argparse


def main():
    parser = argparse.ArgumentParser(description="{title}")
    parser.add_argument("--name", default="world")
    args = parser.parse_args()
    print(f"Hello, {{args.name}}!")


if __name__ == "__main__":
    main()
""",
        "pyproject.toml": f"[project]\nname = \"{spec.target_dir}\"\nversion = \"0.1.0\"\ndescription = \"{title}\"\n",
        "README.md": f"# {title}\n\nAivyOS 生成的 Python CLI 项目。\n",
    }


def _python_api(spec) -> Dict[str, str]:
    title = spec.title
    return {
        "main.py": f"""# {title} — AivyOS 生成 FastAPI 骨架
from fastapi import FastAPI

app = FastAPI(title="{title}")


@app.get("/")
def root():
    return {{"app": "{title}", "status": "ok"}}


@app.get("/health")
def health():
    return {{"status": "healthy"}}
""",
        "requirements.txt": "fastapi>=0.110\nuvicorn>=0.29\n",
        "README.md": f"# {title}\n\n启动：`uvicorn main:app --reload`\n",
    }


def _tauri(spec) -> Dict[str, str]:
    title = spec.title
    return {
        "package.json": json_dumps({
            "name": spec.target_dir, "private": True, "version": "0.1.0", "type": "module",
            "scripts": {"dev": "vite", "build": "vite build", "tauri": "tauri"},
            "dependencies": {"@tauri-apps/api": "^2", "react": "^18.3.1", "react-dom": "^18.3.1"},
            "devDependencies": {"@tauri-apps/cli": "^2", "@vitejs/plugin-react": "^4.3.1", "vite": "^5.4.0"},
        }),
        "vite.config.js": "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\nexport default defineConfig({ plugins: [react()] });\n",
        "index.html": f"<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\"/><title>{title}</title></head><body><div id=\"root\"></div><script type=\"module\" src=\"/src/main.jsx\"></script></body></html>\n",
        "src/main.jsx": "import React from 'react';\nimport ReactDOM from 'react-dom/client';\nimport App from './App.jsx';\nReactDOM.createRoot(document.getElementById('root')).render(<App />);\n",
        "src/App.jsx": f"export default function App() {{\n  return <div><h1>{title}</h1><p>Tauri 2.0 桌面应用骨架（AivyOS 生成）</p></div>;\n}}\n",
        "src-tauri/Cargo.toml": "[package]\nname = \"" + spec.target_dir + "\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n[build-dependencies]\ntauri-build = { version = \"2\", features = [] }\n\n[dependencies]\ntauri = { version = \"2\" }\nserde = { version = \"1\", features = [\"derive\"] }\nserde_json = \"1\"\n\n[lib]\nname = \"app_lib\"\ncrate-type = [\"staticlib\", \"cdylib\", \"rlib\"]\n",
        "src-tauri/src/main.rs": "// Prevents additional console window on Windows in release, DO NOT REMOVE!!\n#![cfg_attr(not(debug_assertions), windows_subsystem = \"windows\")]\n\nfn main() {\n    app_lib::run()\n}\n",
        "src-tauri/src/lib.rs": "#[tauri::command]\nfn greet(name: &str) -> String {\n    format!(\"Hello, {}!\", name)\n}\n\n#[cfg_attr(mobile, tauri::mobile_entry_point)]\npub fn run() {\n    tauri::Builder::default()\n        .invoke_handler(tauri::generate_handler![greet])\n        .run(tauri::generate_context!())\n        .expect(\"error while running tauri application\");\n}\n",
        "src-tauri/tauri.conf.json": '{\n  "$schema": "https://schema.tauri.app/config/2",\n  "productName": "' + title + '",\n  "version": "0.1.0",\n  "identifier": "com.aivyos.gen",\n  "build": {"beforeDevCommand": "npm run dev", "devUrl": "http://localhost:1420", "beforeBuildCommand": "npm run build", "frontendDist": "../dist"},\n  "app": {"windows": [{"title": "' + title + '", "width": 900, "height": 650}]},\n  "bundle": {"active": false}\n}\n',
    }


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


TEMPLATES: Dict[str, TemplateGen] = {
    "static-site": _static,
    "react-web-app": _react,
    "vue-web-app": _vue,
    "nextjs-app": _nextjs,
    "python-cli": _python_cli,
    "python-api": _python_api,
    "tauri-desktop-app": _tauri,
}


def scaffold(project_type: str, spec) -> Dict[str, str]:
    """按类型生成脚手架文件；未知类型回退 static-site。"""
    gen = TEMPLATES.get(project_type, _static)
    return gen(spec)


def list_templates() -> List[str]:
    return list(TEMPLATES.keys())
