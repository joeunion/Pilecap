

def _canary_signs_a_url_in_a_door(client: object, key: str) -> str:
    """Planted violation: issuance, in a DOOR, from a client handed in.

    No import and no setting — the case neither the SDK clause nor the settings
    clause can reach, and the reason the method NAMES are fenced as well. A
    module holding somebody else's client can sign for any key in the bucket, and
    signing is issuance: audited in the seam, behind a service that knows whose
    key it is.
    """
    return client.generate_presigned_url(  # planted violation
        "get_object", Params={"Bucket": "somebody-elses", "Key": key}, ExpiresIn=900
    )
