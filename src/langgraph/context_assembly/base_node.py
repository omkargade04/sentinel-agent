import logging

from src.langgraph.context_assembly.langgraph_workflow import NodeMetrics, NodeResult, WorkflowState
from typing import Dict, Any

class BaseContextAssemblyNode:
    """Base class for workflow nodes."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{name}")

    async def execute(self, state: WorkflowState) -> NodeResult:
        """Execute the node with error handling and metrics."""
        metrics = NodeMetrics(node_name=self.name)

        try:
            # Record input size
            metrics.input_size = self._calculate_state_size(state)

            # Execute node logic
            self.logger.info(f"Executing node: {self.name}")
            result_data = await self._execute_node_logic(state)

            # Record output size and complete metrics
            metrics.output_size = len(str(result_data))
            metrics.mark_complete()

            self.logger.info(
                f"Node {self.name} completed in {metrics.execution_time_seconds:.2f}s"
            )

            return NodeResult(
                success=True,
                data=result_data,
                metrics=metrics
            )

        except Exception as e:
            metrics.error_count = 1
            metrics.mark_complete()

            self.logger.error(f"Node {self.name} failed: {e}")

            return NodeResult(
                success=False,
                data={},
                metrics=metrics,
                error=e
            )

    async def _execute_node_logic(self, state: WorkflowState) -> Dict[str, Any]:
        """Implementation method to be overridden by subclasses."""
        pass

    def _calculate_state_size(self, state: WorkflowState) -> int:
        """Calculate approximate size of state for metrics."""
        try:
            return len(str(state))
        except:
            return 0

