from app.models.knowledge_file import KnowledgeFile
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.knowledge_chunk import KnowledgeChunk


def test_knowledge_four_layer_models_expose_expected_contract():
    assert KnowledgeSource.__tablename__ == "knowledge_source"
    assert KnowledgeVersion.__table__.c.source_id.nullable is False
    assert KnowledgeVersion.__table__.c.parse_status.default.arg == "PENDING"
    assert KnowledgeFile.__table__.c.storage_ref.nullable is False
    assert KnowledgeFile.__table__.c.size_bytes.nullable is False
    assert KnowledgeChunk.__table__.c.version_id.nullable is True
