import hashlib
import hmac

class GithubMiddleware:
    def __init__(self):
        pass

    def verify_webhook_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify GitHub webhook signature"""
        if not signature:
            return False
        
        try:
            sha_name, signature = signature.split('=')
            if sha_name != 'sha256':
                return False
            
            mac = hmac.new(secret.encode(), payload, hashlib.sha256)
            return hmac.compare_digest(mac.hexdigest(), signature)
        except Exception:
            return False