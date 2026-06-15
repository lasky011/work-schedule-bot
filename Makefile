check:
	python3 -m py_compile bot.py app_config.py constants.py keyboards.py sheets_client.py schedule_utils.py smoke_test.py
	python3 smoke_test.py
