import json
import unittest
from urllib.parse import parse_qs, urlparse

from lectureops_agent.services.ncs_official_api import (
    NCSOfficialAPIClient,
    NCSOfficialAPIError,
    parse_official_api_page,
)


XML_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <dataInfo>
    <code>00</code>
    <message>NORMAL SERVICE</message>
    <pageNo>1</pageNo>
    <totCnt>3</totCnt>
    <totalPage>2</totalPage>
  </dataInfo>
  <data>
    <row>
      <ncsClCd>0101010101_17v2</ncsClCd>
      <compUnitName>Project planning</compUnitName>
    </row>
    <row>
      <ncsClCd>2001020205_23v4</ncsClCd>
      <compUnitName>Application software engineering</compUnitName>
    </row>
  </data>
</response>
""".encode("utf-8")


class NCSOfficialAPIClientTests(unittest.TestCase):
    def test_parse_xml_page_preserves_rows_and_pagination(self):
        page = parse_official_api_page(
            XML_PAGE,
            operation="ncsCompeUnitInfo",
            requested_page_no=1,
            requested_page_size=2,
        )

        self.assertEqual(page.total_count, 3)
        self.assertEqual(page.total_pages, 2)
        self.assertTrue(page.has_next)
        self.assertEqual(
            page.items[1]["compUnitName"],
            "Application software engineering",
        )

    def test_parse_json_page_supports_data_info_and_row_shape(self):
        payload = {
            "response": {
                "dataInfo": {
                    "code": "00",
                    "message": "NORMAL",
                    "pageNo": 1,
                    "totCnt": 1,
                    "totalPage": 1,
                },
                "data": {
                    "row": {
                        "ncsClCd": "2001020205_23v4",
                        "compUnitName": "Application software engineering",
                    }
                },
            }
        }

        page = parse_official_api_page(
            json.dumps(payload).encode(),
            operation="ncsCompeUnitInfo",
            requested_page_no=1,
            requested_page_size=100,
        )

        self.assertEqual(page.total_count, 1)
        self.assertEqual(len(page.items), 1)
        self.assertEqual(
            page.items[0]["compUnitName"],
            "Application software engineering",
        )

    def test_parse_json_page_supports_reference_api_shape(self):
        payload = {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL"},
                "body": {
                    "items": {"item": [{"ncsClCd": "NCS-001"}]},
                    "pageNo": 2,
                    "numOfRows": 10,
                    "totalCount": 11,
                },
            }
        }

        page = parse_official_api_page(
            json.dumps(payload).encode(),
            operation="NCS001",
            requested_page_no=2,
            requested_page_size=10,
        )

        self.assertEqual(page.page_no, 2)
        self.assertEqual(page.total_pages, 2)
        self.assertEqual(page.items[0]["ncsClCd"], "NCS-001")

    def test_client_encodes_preencoded_service_key_once(self):
        requested_urls: list[str] = []

        def transport(url: str, timeout: float) -> bytes:
            requested_urls.append(url)
            self.assertEqual(timeout, 30.0)
            return XML_PAGE

        client = NCSOfficialAPIClient(
            service_key="abc%2Fdef%2Bghi",
            transport=transport,
            sleep=lambda _: None,
            monotonic=lambda: 0.0,
        )

        client.fetch_page("ncsCompeUnitInfo", page_no=1, page_size=2)

        query = parse_qs(urlparse(requested_urls[0]).query)
        self.assertEqual(query["serviceKey"], ["abc/def+ghi"])
        self.assertNotIn("%252F", requested_urls[0])

    def test_client_omits_pagination_for_nonpaged_detail_operation(self):
        requested_urls: list[str] = []

        def transport(url: str, timeout: float) -> bytes:
            requested_urls.append(url)
            return XML_PAGE

        client = NCSOfficialAPIClient(
            service_key="key",
            transport=transport,
            sleep=lambda _: None,
            monotonic=lambda: 0.0,
        )

        page = client.fetch_page(
            "ncsScopeInfo",
            page_no=1,
            page_size=100,
            params={"dutyCd": "20010202", "compUnitCd": "05"},
        )

        query = parse_qs(urlparse(requested_urls[0]).query)
        self.assertNotIn("pageNo", query)
        self.assertNotIn("numOfRows", query)
        self.assertEqual(query["dutyCd"], ["20010202"])
        self.assertEqual(query["compUnitCd"], ["05"])
        self.assertFalse(page.has_next)

    def test_api_error_does_not_include_service_key(self):
        error_payload = (
            "<response><header><resultCode>30</resultCode>"
            "<resultMsg>SERVICE KEY IS NOT REGISTERED</resultMsg></header></response>"
        ).encode()

        with self.assertRaises(NCSOfficialAPIError) as raised:
            parse_official_api_page(
                error_payload,
                operation="ncsCompeUnitInfo",
                requested_page_no=1,
                requested_page_size=10,
            )

        self.assertNotIn("secret-key", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
