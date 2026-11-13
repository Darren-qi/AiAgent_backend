import asyncio, logging, traceback, sys
sys.path.insert(0, '/Users/darrenqi/程序/AiAgent/AiAgent_backend_langgraph')
logging.basicConfig(level=logging.INFO)
from app.agent.graphs.main_graph import AgentGraph

async def m():
    g = AgentGraph()
    try:
        r = await g.execute(task="创建一个Flask博客项目",
                            context={"user_id": "dbg", "session_id": "dbg_batch_session"})
        print("RESULT:", {k: r.get(k) for k in ("success", "result", "error", "intent")})
    except Exception:
        traceback.print_exc()

asyncio.run(m())
