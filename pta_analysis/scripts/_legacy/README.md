# _legacy/

2026-07-19 起归档。脚本是从 `pta_analysis/scripts/` 移到这里的早期试验 / 死代码。

## 为什么归档 (不是删除)

- **保留 git 历史** — `git log --all -- scripts/_legacy/xxx.py` 可恢复
- **目录整洁** — 新开发者看 scripts/ 时不再被"这是什么死代码"打断
- **非破坏性** — `git mv` 而非 `git rm`,万一哪天需要恢复 1 行操作搞定

## 为什么是死代码

- **fetch_*.py (3 个)**: 引用已不存在的路径 `/home/admin/.openclaw/workspace/codeman/pta_analysis` (实际是 `Futures_Trading/`)。当前状态跑不了 FileNotFoundError。
- **send_feishu_report.py**: 飞书 webhook (`8148922b-04f5-...`) 孤悬,iv_smile_service.py v2.11.75 已废弃飞书 POST,改用移动端 UI。
- **draw_*.py + chan_structure.py + test_fix.py (4 个)**: 早期 czsc/matplotlib 缠论画图试验,100+ 天没动。

## 如何恢复

```bash
git mv pta_analysis/scripts/_legacy/<file>.py pta_analysis/scripts/<file>.py
git commit -m "restore: <file>.py from _legacy"
```

## 如何清空 _legacy/

如果确认不再需要 (e.g. 半年后仍无人恢复):

```bash
git rm -r pta_analysis/scripts/_legacy/
git commit -m "remove _legacy after long-term deprecation"
```

---

最初归档时跑了 0 引用验证: `grep -rln` 整个 `pta_analysis/`,8 个文件 0 引用。归档决策见对话历史 (2026-07-19 飞书)。