AI-cloud-cost-detective - RequestFlow
① User ─·─·─► React ─·─·─► FastAPI Auth ─·─·─► JWT (PostgreSQL)

② User selects AWS Region ─·─·─► Python Backend

③ Python ─·─·─► AWS CLI + Boto3 ─·─·─► Fetches AWS resources in selected region

④ Python ─·─·─► FastAPI WebSocket ─·─·─► React (live progress)

⑤ Python ─·─·─► Google Gemini API ─·─·─► Cost analysis

⑥ Python ─·─·─► PostgreSQL ─·─·─► Stores analysis history

⑦ React ◄·─·─·─ Final report with suggestions & fixes