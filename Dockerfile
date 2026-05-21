FROM python:3.9-slim
WORKDIR /app
COPY . .
RUN pip install -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
EXPOSE 5000
CMD ["python", "backend/app.py"]