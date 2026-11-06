PYTHON := .venv/bin/python

.DEFAULT_GOAL := shell
.PHONY: shell lint lint-fix test setup

# 交互菜单：抓取、整理、检查、更新数据库、发布
shell: | $(PYTHON)
	@$(PYTHON) scripts/shell.py

lint: | $(PYTHON)
	@$(PYTHON) scripts/lint.py

# 自动修复能按规则修好的格式问题（含 DLC），再检查一遍
lint-fix: | $(PYTHON)
	@$(PYTHON) scripts/lint.py --dlc --fix

test: | $(PYTHON)
	@$(PYTHON) -m unittest discover scripts/tests

# requirements.txt 有变化时手动运行
setup: | $(PYTHON)
	$(PYTHON) -m pip install -r requirements.txt

# 只在没有虚拟环境时创建，已有的不会重建
$(PYTHON):
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt
