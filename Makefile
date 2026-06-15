check:
	python3 -m py_compile bot.py app_config.py constants.py keyboards.py sheets_client.py schedule_utils.py db.py repositories/users_repo.py repositories/shifts_repo.py smoke_test.py
	python3 smoke_test.py
