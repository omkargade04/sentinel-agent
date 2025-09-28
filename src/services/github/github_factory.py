from typing import Dict, Any
from src.services.github.installation_service import InstallationRepositoriesService, InstallationService
from src.utils.logging.otel_logger import logger


class GithubFactory:
    def __init__(self):
        pass

    def handle_callback(self, code: str, installation_id: str) -> Dict[str, Any]:
        """Handle GitHub App installation callback - UX only, webhook does the real work"""
        try:
            logger.info(f"GitHub installation callback received for installation: {installation_id}")
            
            return {
                "status": "success", 
                "message": "🎉 Sentinel has been successfully installed! Your repositories are being indexed.",
                "installation_id": installation_id,
                "redirect_url": f"/callback?installation_id={installation_id}",
                "next_steps": [
                    "Your repositories are being indexed in the background",
                    "You'll receive notifications when indexing is complete", 
                    "Start creating pull requests to see Sentinel in action!"
                ]
            }
        except Exception as e:
            logger.error(f"Error handling GitHub callback: {str(e)}")
            return {
                "status": "error",
                "message": "There was an issue with the installation. Please try again or contact support."
            }
        
    async def process_webhook(self, body: Dict[str, Any], event_type: str) -> Dict[str, Any]:
        """Process GitHub webhook events"""
        try:
            logger.info(f"Processing GitHub webhook event: {event_type}")
            
            if event_type == "installation":
                action = body.get("action")
                if action == "created":
                    installation_service = InstallationService()
                    return await installation_service.process_installation_created(body)
                elif action == "deleted":
                    installation_service = InstallationService()
                    return await installation_service.process_installation_deleted(body)
                else:
                    logger.warning(f"Unhandled installation action: {action}")
            
            elif event_type == "installation_repositories":
                action = body.get("action")
                if action in ["added", "removed"]:
                    installation_repositories_service = InstallationRepositoriesService()
                    return await installation_repositories_service.process_repositories_changed(body, action)
                else:
                    logger.warning(f"Unhandled installation_repositories action: {action}")
            
            elif event_type == "pull_request":
                # TODO: Implement PR webhook handling for code reviews
                logger.info("PR webhook received - not implemented yet")
                
            else:
                logger.info(f"Unhandled webhook event type: {event_type}")
            
            return {
                "status": "success",
                "message": f"Webhook {event_type} processed successfully"
            }
            
        except Exception as e:
            logger.error(f"Error processing webhook {event_type}: {str(e)}")
            return {
                "status": "error",
                "message": f"Failed to process webhook {event_type}"
            }