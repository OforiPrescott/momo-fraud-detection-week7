"""
Column vocabulary for incoming data.

Real-world exports never use PaySim's exact column names, so every
upload / database table / API response is passed through
``canonicalise_columns`` first. Matching ignores case, spaces, dashes and
underscores ("Old Balance Org", "old_balance_org" and "oldbalanceOrg" are
the same column).
"""
import re

import pandas as pd

# canonical name -> accepted aliases (any spelling; compared in squashed form)
ALIASES = {
    "step": ["step", "timestep", "hourstep", "hour_step"],
    "type": ["type", "transactiontype", "txntype", "trxtype", "transtype", "transactioncategory", "trantype"],
    "amount": ["amount", "amt", "value", "transactionamount", "txnamount", "trxamount"],
    "nameOrig": ["nameorig", "origin", "originaccount", "sender", "senderid", "senderaccount", "source",
                 "sourceaccount", "fromaccount", "from", "customerid", "accountid", "account", "msisdn", "orig"],
    "nameDest": ["namedest", "destination", "destinationaccount", "receiver", "receiverid", "receiveraccount",
                 "recipient", "recipientaccount", "toaccount", "to", "beneficiary", "dest", "merchant", "agentid"],
    "oldbalanceOrg": ["oldbalanceorg", "oldbalanceorig", "senderbalancebefore", "balancebefore", "oldbalance",
                      "originbalancebefore", "prebalance"],
    "newbalanceOrig": ["newbalanceorig", "newbalanceorg", "senderbalanceafter", "balanceafter", "newbalance",
                       "originbalanceafter", "postbalance"],
    "oldbalanceDest": ["oldbalancedest", "receiverbalancebefore", "destbalancebefore", "destinationbalancebefore"],
    "newbalanceDest": ["newbalancedest", "receiverbalanceafter", "destbalanceafter", "destinationbalanceafter"],
    "timestamp": ["timestamp", "datetime", "date", "time", "transactiontime", "txntime", "createdat", "eventtime",
                  "transactiondate", "txndate"],
    "device_id": ["deviceid", "device", "devicefingerprint", "imei", "handsetid"],
    "sim_change": ["simchange", "simchangeevent", "simswap", "simswapped", "simchanged", "recentsimchange"],
    "isFraud": ["isfraud", "fraud", "fraudflag", "isfraudulent", "confirmedfraud"],
    "any_attack_flag": ["anyattackflag", "attackflag", "isattack"],
    "label": ["label", "target", "class", "outcome", "ismalicious"],
    "sim_swap_takeover": ["simswaptakeover"],
    "pin_sharing_flag": ["pinsharingflag", "pinsharing"],
    "agent_collusion_flag": ["agentcollusionflag", "agentcollusion"],
}

# access-event files (device / SIM layer, as produced by access_event_generator.py)
EVENT_ALIASES = {
    "account_id": ["accountid", "account", "nameorig", "msisdn", "customerid", "sender", "senderid"],
    "device_id": ["deviceid", "device", "devicefingerprint", "imei"],
    "sim_change_event": ["simchangeevent", "simchange", "simswap", "simswapped"],
    "step": ["step", "timestep"],
    "timestamp": ["timestamp", "datetime", "logintimestamp", "eventtime", "date"],
}

TYPE_MAP = {
    "CASHOUT": "CASH_OUT", "WITHDRAWAL": "CASH_OUT", "WITHDRAW": "CASH_OUT", "AGENTWITHDRAWAL": "CASH_OUT",
    "CASHIN": "CASH_IN", "DEPOSIT": "CASH_IN", "TOPUP": "CASH_IN", "AGENTDEPOSIT": "CASH_IN",
    "TRANSFER": "TRANSFER", "SEND": "TRANSFER", "SENDMONEY": "TRANSFER", "P2P": "TRANSFER", "PEERTRANSFER": "TRANSFER",
    "PAYMENT": "PAYMENT", "MERCHANTPAYMENT": "PAYMENT", "BILLPAYMENT": "PAYMENT", "PAYBILL": "PAYMENT",
    "AIRTIME": "PAYMENT", "DEBIT": "DEBIT",
}
KNOWN_TYPES = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"]


def squash(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _reverse(alias_map, extra_names=()):
    rev = {}
    for canon, names in alias_map.items():
        rev[squash(canon)] = canon
        for n in names:
            rev.setdefault(squash(n), canon)
    for n in extra_names:
        rev.setdefault(squash(n), n)
    return rev


def canonicalise_columns(df: pd.DataFrame, feature_cols=(), alias_map=None) -> pd.DataFrame:
    """Rename recognised columns to canonical names; first match wins on duplicates."""
    rev = _reverse(alias_map or ALIASES, feature_cols)
    new_names, seen = [], set()
    keep = []
    for c in df.columns:
        canon = rev.get(squash(c), None)
        if canon is None:
            continue  # unrecognised columns are dropped: the analysis never needs them
        if canon in seen:
            continue
        seen.add(canon)
        new_names.append(canon)
        keep.append(c)
    out = df[keep].copy()
    out.columns = new_names
    return out


def normalise_types(series: pd.Series):
    """Map free-text transaction types onto PaySim's five. Returns (series, n_unrecognised)."""
    raw = series.astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
    mapped = raw.map(TYPE_MAP)
    unknown = mapped.isna()
    mapped = mapped.where(~unknown, series.astype(str).str.upper().str.strip())
    return mapped, int(unknown.sum())
