project_create("fastapi_project")

file_write(path="requirements.txt", content="""fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
""")

file_write(path="main.py", content="""from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import items, users
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Set up CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include API routers
app.include_router(items.router, prefix=settings.API_V1_STR, tags=["items"])
app.include_router(users.router, prefix=settings.API_V1_STR, tags=["users"])

@app.get("/")
async def root():
    return {
        "message": "Welcome to FastAPI Project",
        "version": settings.VERSION,
        "docs": "/docs",
        "redoc": "/redoc"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
""")

file_write(path="app/__init__.py", content="""# FastAPI Application Package
""")

file_write(path="app/api/__init__.py", content="""# API Routes Package
""")

file_write(path="app/api/items.py", content="""from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

class Item(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    tax: Optional[float] = None

# In-memory database simulation
items_db = [
    Item(id=1, name="Laptop", description="High-performance laptop", price=1500.00, tax=0.15),
    Item(id=2, name="Mouse", description="Wireless mouse", price=25.99, tax=0.10),
    Item(id=3, name="Keyboard", description="Mechanical keyboard", price=89.99, tax=0.12),
]

@router.get("/items/", response_model=List[Item])
async def read_items(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=100, description="Maximum number of items to return")
):
    """Get list of items with pagination"""
    return items_db[skip:skip + limit]

@router.get("/items/{item_id}", response_model=Item)
async def read_item(item_id: int):
    """Get a specific item by ID"""
    for item in items_db:
        if item.id == item_id:
            return item
    raise HTTPException(status_code=404, detail="Item not found")

@router.post("/items/", response_model=Item, status_code=201)
async def create_item(item: Item):
    """Create a new item"""
    # Check if item already exists
    for existing_item in items_db:
        if existing_item.id == item.id:
            raise HTTPException(status_code=400, detail="Item with this ID already exists")
    
    items_db.append(item)
    return item

@router.put("/items/{item_id}", response_model=Item)
async def update_item(item_id: int, item: Item):
    """Update an existing item"""
    if item_id != item.id:
        raise HTTPException(status_code=400, detail="Item ID mismatch")
    
    for i, existing_item in enumerate(items_db):
        if existing_item.id == item_id:
            items_db[i] = item
            return item
    
    raise HTTPException(status_code=404, detail="Item not found")

@router.delete("/items/{item_id}", status_code=204)
async def delete_item(item_id: int):
    """Delete an item"""
    for i, item in enumerate(items_db):
        if item.id == item_id:
            items_db.pop(i)
            return
    
    raise HTTPException(status_code=404, detail="Item not found")
""")

file_write(path="app/api/users.py", content="""from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

router = APIRouter()

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    is_active: bool = True

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int

    class Config:
        from_attributes = True

# In-memory database simulation
users_db = []
next_user_id = 1

@router.get("/users/", response_model=List[User])
async def read_users():
    """Get all users"""
    return users_db

@router.get("/users/{user_id}", response_model=User)
async def read_user(user_id: int):
    """Get a specific user by ID"""
    for user in users_db:
        if user.id == user_id:
            return user
    raise HTTPException(status_code=404, detail="User not found")

@router.post("/users/", response_model=User, status_code=201)
async def create_user(user: UserCreate):
    """Create a new user"""
    global next_user_id
    
    # Check if email already exists
    for existing_user in users_db:
        if existing_user.email == user.email:
            raise HTTPException(status_code=400, detail="Email already registered")
    
    new_user = User(
        id=next_user_id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active
    )
    users_db.append(new_user)
    next_user_id += 1
    return new_user

@router.put("/users/{user_id}", response_model=User)
async def update_user(user_id: int, user_update: UserBase):
    """Update user information"""
    for i, user in enumerate(users_db):
        if user.id == user_id:
            # Check if email is being changed to an existing one
            if user_update.email != user.email:
                for other_user in users_db:
                    if other_user.email == user_update.email and other_user.id != user_id:
                        raise HTTPException(status_code=400, detail="Email already registered")
            
            updated_user = User(
                id=user_id,
                email=user_update.email,
                full_name=user_update.full_name,
                is_active=user_update.is_active
            )
            users_db[i] = updated_user
            return updated_user
    
    raise HTTPException(status_code=404, detail="User not found")

@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int):
    """Delete a user"""
    for i, user in enumerate(users_db):
        if user.id == user_id:
            users_db.pop(i)
            return
    
    raise HTTPException(status_code=404, detail="User not found")
""")

file_write(path="app/core/__init__.py", content="""# Core Configuration Package
""")

file_write(path="app/core/config.py", content="""from typing import List, Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Project settings
    PROJECT_NAME: str = "FastAPI Project"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # CORS settings
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]
    
    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
""")

file_write(path="app/models/__init__.py", content="""# Data Models Package
""")

file_write(path="app/models/item.py", content="""from pydantic import BaseModel
from typing import Optional

class ItemBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    tax: Optional[float] = None

class ItemCreate(ItemBase):
    pass

class ItemUpdate(ItemBase):
    pass

class Item(ItemBase):
    id: int
    
    class Config:
        from_attributes = True
""")

file_write(path="app/models/user.py", content="""from pydantic import BaseModel, EmailStr
from typing import Optional

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    is_active: bool = True

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

class User(UserBase):
    id: int
    
    class Config:
        from_attributes = True
""")

file_write(path="README.md", content="""# FastAPI Project

A modern, fast web framework for building APIs with Python.

## Features

- FastAPI with automatic interactive API documentation
- Modular API structure
- Pydantic data validation
- CORS middleware support
- Example CRUD endpoints for Items and Users

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

### Development mode (with auto-reload):
```bash
python main.py
```

Or using uvicorn directly:
```bash
uvicorn main:app --reload
```

## API Documentation

Once the application is running:

- Interactive API docs: http://localhost:8000/docs
- Alternative API docs: http://localhost:8000/redoc
- OpenAPI schema: http://localhost:8000/api/v1/openapi.json

## API Endpoints

### Items
- `GET /api/v1/items/` - List all items
- `GET /api/v1/items/{item_id}` - Get specific item
- `POST /api/v1/items/` - Create new item
- `PUT /api/v1/items/{item_id}` - Update item
- `DELETE /api/v1/items/{item_id}` - Delete item

### Users
- `GET /api/v1/users/` - List all users
- `GET /api/v1/users/{user_id}` - Get specific user
- `POST /api/v1/users/` - Create new user
- `PUT /api/v1/users/{user_id}` - Update user
- `DELETE /api/v1/users/{user_id}` - Delete user

## Project Structure

```
fastapi_project/
├── main.py              # Application entry point
├── requirements.txt     # Dependencies
├── README.md           # This file
└── app/                # Application package
    ├── __init__.py
    ├── api/            # API routes
    │   ├── __init__.py
    │   ├── items.py    # Items endpoints
    │   └── users.py    # Users endpoints
    ├── core/           # Core configuration
    │   ├── __init__.py
    │   └── config.py   # Settings
    └── models/         # Data models
        ├── __init__.py
        ├── item.py     # Item models
        └── user.py     # User models
```

## Testing the API

You can test the API using curl or any HTTP client:

```bash
# Get all items
curl http://localhost:8000/api/v1/items/

# Create a new item
curl -X POST http://localhost:8000/api/v1/items/ \
  -H "Content-Type: application/json" \
  -d '{"id": 4, "name": "Monitor", "price": 299.99}'
```

## License

MIT
""")

STAGE_DONE: development

【工具执行结果】
✅ 创建项目 'fastapi_project'
📄 创建文件 'requirements.txt'
📄 创建文件 'main.py'
📄 创建文件 'app/__init__.py'
📄 创建文件 'app/api/__init__.py'
📄 创建文件 'app/api/items.py'
📄 创建文件 'app/api/users.py'
📄 创建文件 'app/core/__init__.py'
📄 创建文件 'app/core/config.py'
📄 创建文件 'app/models/__init__.py'
📄 创建文件 'app/models/item.py'
📄 创建文件 'app/models/user.py'
📄 创建文件 'README.md'