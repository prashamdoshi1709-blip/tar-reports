import sys, copy
sys.path.insert(0, "tools")
import filing_contract as f
ok = {"schema": 4, "claude_verification": {k: True for k in f.V4_FLAGS},
      "vitti_source": {"basis": "VITTI_DAILY_MOVER", "email_message_id": "m1", "pdf_name": "DNL.pdf",
                       "pdf_sha256": "a" * 64, "independently_verified": False}}
n = 0
def bad(P, code):
    global n
    try: f.validate(P)
    except f.ContractError as e:
        assert e.code == code, (e.code, code); n += 1; return
    raise AssertionError("accepted " + code)
assert f.validate(ok)["schema"] == 4; n += 1
for k in f.V4_FLAGS:
    P = copy.deepcopy(ok); P["claude_verification"][k] = False; bad(P, "V4_FLAGS")
P = copy.deepcopy(ok); P["vitti_source"]["basis"] = "X"; bad(P, "V4_SOURCE")
P = copy.deepcopy(ok); P["vitti_source"]["independently_verified"] = True; bad(P, "V4_SOURCE")
P = copy.deepcopy(ok); P["vitti_source"]["pdf_sha256"] = "zz"; bad(P, "V4_SOURCE")
P = copy.deepcopy(ok); del P["vitti_source"]["email_message_id"]; bad(P, "V4_SOURCE")
P = copy.deepcopy(ok); P["schema"] = 5; bad(P, "UNRECOGNISED_SCHEMA")
print("schema4 OK", n, "checks")
