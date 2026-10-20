# tools —— 一次性历史脚本

这里的 `tools_*.py` 是项目早期探索时写的临时脚本：数据探查、接口试探、
对比验证、出图。**不参与主流程，也不保证还能跑**——它们写于目录重组之前，
路径假设（`ROOT = Path(".")`、`hubei-261013-free-OpenMap/hubei.gpkg`）已经变了。

留在仓库里是为了两件事：

1. 记录当初怎么试错（答辩/复盘时可以引用）；
2. 万一需要某个一次性分析，可以直接翻出来改。

## 如果确实要运行

先改脚本头部的路径，比如：

```python
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
```

或者直接参考 `backend/scripts/` 里同名逻辑的正式实现。

## 想看现在的规范实现

- 数据准备：`backend/scripts/prepare_dataset.py`
- 数据体检：`backend/scripts/data_audit.py`
- 建图与等时圈：`backend/app/`
