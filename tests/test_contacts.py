"""Contact identity resolution across search and enumerated pages."""
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from test_beeper import RuntimeFixture
from beeper import Failure


class ContactTests(RuntimeFixture):
    def setUp(self):
        super().setUp()
        self.account = {"accountID": "network-1", "network": "Example", "user": {"id": "self"}}
        self.contact = {"id": "opaque-user", "fullName": "Example Person", "phoneNumber": "+10000000000"}

    def show(self, args, responses):
        with patch.object(self.runtime, "api", side_effect=responses) as api:
            result = self.runtime.command(["contacts", "show", *args])
        return result, api.call_args_list

    def test_original_search_query_resolves_exact_id_without_list(self):
        result, calls = self.show(["opaque-user", "--account", "Example", "--query", "Example Person"],
                                 [[self.account], {"items": [self.contact, self.contact]}])
        self.assertEqual(result, {"accountID": "network-1", "contact": self.contact})
        self.assertEqual(len(calls), 2)
        self.assertEqual(parse_qs(urlsplit(calls[1].args[1]).query), {"query": ["Example Person"]})

    def test_full_name_and_phone_are_recognized(self):
        for selector in ["Example Person", "+10000000000"]:
            result, _ = self.show([selector], [[self.account], {"items": [self.contact]}])
            self.assertEqual(result["contact"]["id"], "opaque-user")

    def test_opaque_id_can_be_found_after_first_list_page(self):
        result, calls = self.show(["opaque-user"], [[self.account], {"items": []},
            {"items": [{"id": "other", "fullName": "Other"}], "hasMore": True, "oldestCursor": "next+/page"},
            {"items": [self.contact], "hasMore": False}])
        self.assertEqual(result["contact"]["id"], "opaque-user")
        self.assertEqual(parse_qs(urlsplit(calls[-1].args[1]).query)["cursor"], ["next+/page"])

    def test_multiple_accounts_and_duplicate_names_are_ambiguous(self):
        variants = [
            ([[self.account], {"items": [self.contact, {**self.contact, "id": "different-user"}]}], ["Example Person"]),
            ([[self.account, {**self.account, "accountID": "network-2"}], {"items": [self.contact]}, {"items": [self.contact]}], ["opaque-user"]),
        ]
        for responses, args in variants:
            with self.assertRaises(Failure) as error:
                self.show(args, responses)
            self.assertEqual(error.exception.code, "ambiguous_contact")

    def test_empty_enumeration_is_unresolved_not_no_contacts(self):
        with self.assertRaises(Failure) as error:
            self.show(["opaque-user"], [[self.account], {"items": []}, {"items": [], "hasMore": False}])
        self.assertEqual(error.exception.code, "contact_unresolved")
        self.assertIn("--query", str(error.exception))

    def test_opaque_ids_are_case_sensitive_and_exact_account_wins(self):
        other_account = {**self.account, "accountID": "NETWORK-1"}
        other_contact = {**self.contact, "id": "OPAQUE-USER"}
        result, calls = self.show(["opaque-user", "--account", "network-1"],
            [[self.account, other_account], {"items": [other_contact, self.contact]}])
        self.assertEqual(result["contact"]["id"], "opaque-user")
        self.assertEqual(result["accountID"], "network-1")
        self.assertEqual(len(calls), 2)

    def test_budget_and_wrong_account_fail_before_broad_read(self):
        with self.assertRaises(Failure) as error:
            self.show(["opaque-user", "--max-pages", "1"], [[self.account]])
        self.assertEqual(error.exception.code, "contact_lookup_incomplete")
        with self.assertRaises(Failure) as error:
            self.show(["opaque-user", "--account", "missing"], [[self.account]])
        self.assertEqual(error.exception.code, "account_not_found")
