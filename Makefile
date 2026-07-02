check:
	python3 -m py_compile bot.py admin_bot.py app_config.py constants.py sheets_client.py schedule_utils.py db.py states.py ui_utils.py departments_manager.py fsm_context.py repositories/users_repo.py repositories/shifts_repo.py repositories/sheet_periods_repo.py repositories/admin_repo.py repositories/admin_log_repo.py smoke_test.py
	python3 -m compileall -q keyboards routers services
	python3 smoke_test.py
