import importlib.util
import os
from pathlib import Path


def test_verification_disables_real_mail_and_models(monkeypatch):
    path=Path(__file__).resolve().parents[2]/'scripts'/'m3_verify.py'
    spec=importlib.util.spec_from_file_location('m3_verify_safety',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(os,'environ',os.environ.copy())
    monkeypatch.setenv('SMTP_ENABLED','true')
    monkeypatch.setenv('SMTP_HOST','external.example.test')
    monkeypatch.setenv('SMTP_PASSWORD','sentinel-private')
    module.configure()
    assert os.environ['SMTP_ENABLED']=='false'
    assert os.environ['SMTP_HOST']=='127.0.0.1'
    assert os.environ['SMTP_PASSWORD']==''
    assert os.environ['LLM_PROVIDER']==os.environ['EMBEDDING_PROVIDER']=='mock'
