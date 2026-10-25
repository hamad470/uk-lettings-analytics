all: data pipeline dashboard

data:
	python src/generate_data.py

pipeline:
	python src/pipeline.py

dashboard:
	python src/build_dashboard.py

test:
	pytest -q

app:
	streamlit run app.py
