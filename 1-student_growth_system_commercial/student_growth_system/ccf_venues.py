from typing import Optional

CCF_VENUE_RANKS = {
    "SIGCOMM": "A", "MOBICOM": "A", "INFOCOM": "A", "NSDI": "A", "SOSP": "A", "OSDI": "A",
    "ASPLOS": "A", "VLDB": "A", "SIGMOD": "A", "ICDE": "A", "KDD": "A", "WWW": "A",
    "AAAI": "A", "IJCAI": "A", "NeurIPS": "A", "ICML": "A", "ACL": "A", "CVPR": "A", "ICCV": "A", "ECCV": "A",
    "NDSS": "A", "S&P": "A", "USENIX SECURITY": "A", "CCS": "A",
    "DASFAA": "B", "CIKM": "B", "WSDM": "B", "ICDM": "B", "EMNLP": "B", "COLING": "B",
    "ICSE": "A", "FSE": "A", "ASE": "A", "ISSTA": "A", "SANER": "B", "ICPC": "B",
    "PAKDD": "C", "APWEB": "C", "NLPCC": "C", "PRICAI": "C",
}


def guess_ccf_rank(venue: Optional[str]) -> Optional[str]:
    if not venue:
        return None
    upper = venue.upper()
    if "WORKSHOP" in upper:
        return None
    for k, v in CCF_VENUE_RANKS.items():
        if k.upper() in upper:
            return v
    return None
