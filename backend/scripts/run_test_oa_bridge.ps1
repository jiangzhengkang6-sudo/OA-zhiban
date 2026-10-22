param([string]$ApiKey = "test-oa-local-key-20261021", [int]$Port = 8091)
$env:TEST_OA_API_KEY = $ApiKey
$env:TEST_OA_PORT = $Port
Write-Host "Test OA Bridge: http://127.0.0.1:$Port"
Write-Host "OA_BASE_URL=http://127.0.0.1:$Port"
Write-Host "TEST_OA_API_KEY configured (token value is not printed)"
python -m uvicorn scripts.test_oa_bridge:app --host 127.0.0.1 --port $Port
