"""Maintenance mode must block writes before Supabase-to-local DB cutover."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from scripts.oracle_runner.oracle_middleware import (
    OracleEdgeOnlyMiddleware, OracleMigrationMaintenanceMiddleware,
)

class OracleMigrationFreezeTests(SimpleTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.flag=Path(self.temp.name)/"maintenance.flag"
        self.flag.write_text("freeze")
        self.patch=patch.object(OracleMigrationMaintenanceMiddleware,"FLAG",self.flag)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.middleware=OracleEdgeOnlyMiddleware(
            OracleMigrationMaintenanceMiddleware(lambda _:HttpResponse("OK"))
        )
        self.factory=RequestFactory()

    def request(self,path,method="get",headers=None):
        headers=headers or {}
        return getattr(self.factory,method)(
            path, **{"HTTP_"+name.upper().replace("-","_"):value for name,value in headers.items()}
        )

    def test_blocks_public_post_and_get(self):
        for method,path in (("get","/dogs/"),("post","/accounts/login/"),
                            ("post","/accounts/paystack/webhook/")):
            response=self.middleware(self.request(path,method,{"X-CCA-Edge":"1",
                "X-CCA-Origin-Secret":settings.SECRET_KEY}))
            self.assertEqual(response.status_code,503)
            self.assertEqual(response["Retry-After"],"120")
            self.assertIn("no-store",response["Cache-Control"])

    def test_health_and_trusted_bypass(self):
        self.assertEqual(self.middleware(self.request("/healthz/")).status_code,200)
        headers={"X-CCA-Edge":"1","X-CCA-Origin-Secret":settings.SECRET_KEY,
                 "X-CCA-Maintenance-Probe":settings.SECRET_KEY}
        self.assertEqual(self.middleware(self.request("/accounts/login/","get",headers)).status_code,200)

    def test_permission_error_cannot_allow_requests_through(self):
        headers={"X-CCA-Edge":"1","X-CCA-Origin-Secret":settings.SECRET_KEY}
        with patch.object(Path, "exists", side_effect=PermissionError("SELinux denied")):
            response=self.middleware(self.request("/member/submit/","post",headers))
        self.assertEqual(response.status_code,503)
        self.assertEqual(response["Retry-After"],"120")

    def test_direct_origin_cannot_bypass(self):
        self.assertEqual(self.middleware(self.request("/accounts/login/")).status_code,403)

    def test_normal_operations_resume_after_root_flag_removed(self):
        self.flag.unlink()
        headers={"X-CCA-Edge":"1","X-CCA-Origin-Secret":settings.SECRET_KEY}
        self.assertEqual(self.middleware(self.request("/dogs/","get",headers)).status_code,200)
