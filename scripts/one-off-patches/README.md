# 一次性补丁脚本归档

项目演进过程中用于批量修正代码/配置的一次性脚本，按使用时间归档，**不参与运行**。
保留是为了记录问题排查路径，不代表当前实现。

- `_fix_rag_load.py` / `_fix_retrieval.py` / `_fix_score.py` / `_fix_weight.py`
  / `_patch_*rag*.py` —— RAG 检索与相关性打分的迭代过程
- `_fix_alias*.py` —— 别名映射（社区口语 → wiki 标题）的修正
- `patch_signin_b1.py` / `patch_backlink.py` / `patch_followup.py` / `patch_visible.py`
  —— 登录、回链、追问、可见性流程调整
- `patch_b5.py` / `_fix_literal.py` / `_fix_pool.py` —— 字面匹配与连接池相关修复

常用运维工具在上一级 `scripts/`：`set_qwen_key.py`、`gunicorn-memory-note.txt`
