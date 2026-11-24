"""Page 6: Settings (Keyring DeepSeek Key, Endpoint Config, Desktop App Controls, Doctor)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import streamlit as st

from qcai.config import default_config_path
from qcai.launcher import create_desktop_shortcut, get_runtime_status, stop_web_assistant
from qcai.remote import run_doctor
from web.state import get_db_path, has_deepseek_key, load_app_settings, save_deepseek_key
from web.theme import render_page_hero


def _update_deepseek_endpoint(model: str, base_url: str) -> None:
    """Safely update only model & base_url in [deepseek] section of config/settings.toml."""
    cfg_path = default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    safe_model = model.strip() or "deepseek-chat"
    safe_url = base_url.strip()
    new_block = f'[deepseek]\napi_key = ""\nmodel = "{safe_model}"\nbase_url = "{safe_url}"\n'
    if re.search(r"(?ms)^\[deepseek\].*?(?=^\[|\Z)", text):
        updated = re.sub(r"(?ms)^\[deepseek\].*?(?=^\[|\Z)", new_block, text)
    else:
        updated = (text.rstrip() + "\n\n" if text.strip() else "") + new_block
    cfg_path.write_text(updated, encoding="utf-8")


def render_settings_page() -> None:
    render_page_hero(
        "6. 系统设置与环境自检",
        "安全管理 DeepSeek API 凭据（写入系统密钥环绝不回显）、桌面封装快捷方式以及本机/远程运行环境诊断。",
    )
    settings = load_app_settings()

    left_col, right_col = st.columns(2)

    with left_col, st.container(border=True):
        st.subheader("🤖 DeepSeek AI 接口配置")
        st.text(f"API Key 状态：{'✅ 已设置' if has_deepseek_key(settings) else '❌ 未设置'}")
        new_key = st.text_input("输入新的 DeepSeek API Key", type="password", key="set_ds_key")
        if st.button("保存 Key 到系统密钥环", use_container_width=True, key="btn_save_key"):
            if new_key.strip():
                save_deepseek_key(new_key)
                st.success("已安全保存至系统密钥环（界面不回显）。")
            else:
                st.warning("Key 不能为空。")

        st.divider()
        model_in = st.text_input(
            "模型名称 (model)",
            value=settings.deepseek.model or "deepseek-chat",
            key="set_ds_model",
        )
        url_in = st.text_input(
            "自定义兼容接口地址 (base_url，留空使用官方地址)",
            value=settings.deepseek.base_url,
            key="set_ds_url",
        )
        if st.button("保存模型与接口地址", use_container_width=True, key="btn_save_ds_ep"):
            _update_deepseek_endpoint(model_in, url_in)
            st.success("已更新 `[deepseek]` 的模型与接口地址（SSH 配置不受影响）。")

    with right_col, st.container(border=True):
        st.subheader("🖥️ 本地软件路径与桌面封装")
        st.text(f"SSH 配置状态：{'✅ 已配置' if settings.ssh.host else '⚪ 未配置'}")
        st.text(f"Origin 路径：{settings.origin.executable or '未配置'}")
        st.text(f"VMD 路径：{settings.vmd.executable or '未配置'}")

        st.divider()
        rt = get_runtime_status(get_db_path())
        st.text(
            f"后台服务状态：{'🟢 运行中 (端口 ' + str(rt.get('port')) + ')' if rt.get('running') else '⚪ 前台/测试模式'}"
        )
        d1, d2 = st.columns(2)
        if sys.platform == "win32" and d1.button(
            "📌 生成桌面快捷方式", use_container_width=True, key="btn_create_lnk"
        ):
            try:
                lnk = create_desktop_shortcut()
                st.success(f"已生成桌面图标：{lnk.name}")
            except Exception as exc:
                st.error(f"生成失败：{exc}")
        if d2.button("🛑 停止后台服务", use_container_width=True, key="btn_stop_bg"):
            info = stop_web_assistant(get_db_path(), include_orphans=True)
            st.info(f"停止结果：{info['stopped_pids'] or '当前无独立后台记录'}")

    with st.container(border=True):
        st.subheader("🩺 环境诊断 (`qcai doctor`)")
        local_only = st.checkbox("仅检测本机环境（跳过 SSH）", value=True, key="set_local_only")
        if st.button("一键检测环境", type="primary", key="btn_run_doctor"):
            with st.spinner("正在执行环境自检..."):
                items, _ = run_doctor(
                    settings, local_only=local_only, output_doc=Path("docs/environment.md")
                )
            for item in items:
                mark = "✅" if item.ok else "❌"
                st.write(
                    f"{mark} **{item.name}**: {item.detail}"
                    + (f" — {item.suggestion}" if not item.ok else "")
                )


render_settings_page()
