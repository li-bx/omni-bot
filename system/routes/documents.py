"""
文档上传 & 知识库管理 API
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Request
from ..shared import dm, check_auth
from ..config import scan_upload_documents

router = APIRouter()


@router.post("/documents/upload")
async def upload_document(file: UploadFile = File(...), domain: str = "通用", request: Request = None):
    """上传知识库文档，可指定领域分类"""
    if request and not check_auth(request):
        raise HTTPException(status_code=401, detail="请先登录")
    content = await file.read()
    return dm.upload_document(file.filename, content, domain=domain)


@router.get("/documents")
async def list_documents():
    """列出已上传文档"""
    return dm.list_documents()


@router.get("/documents/domains")
async def list_domains():
    """列出所有文档领域"""
    entries = scan_upload_documents()
    domains = sorted(set(e["domain"] for e in entries))
    return {"domains": domains}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档"""
    return dm.delete_document(doc_id)


@router.post("/documents/{doc_id}/parse")
async def parse_document(doc_id: str):
    """解析文档为段落"""
    return dm.parse_document_to_chunks(doc_id)
