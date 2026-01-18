"""
Context Analyzer Node Implementation

Node 1 in the Review Generation workflow.
Analyzes context pack for technical patterns, complexity, and review focus areas.
"""

import logging
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from dataclasses import dataclass

from src.langgraph.review_generation.base_node import BaseReviewGenerationNode
from src.langgraph.review_generation.circuit_breaker import CircuitBreaker
from src.langgraph.review_generation.schema import (
    AnalyzedContext,
    TechnicalInsight,
    ReviewFocusArea,
)

logger = logging.getLogger(__name__)


# ============================================================================
# FRAMEWORK AND PATTERN DETECTION
# ============================================================================

@dataclass
class FrameworkSignature:
    """Signature for detecting a framework/library."""
    name: str
    category: str  # web, testing, data, orm, async, etc.
    file_patterns: List[str]  # File path patterns
    import_patterns: List[str]  # Import statement patterns
    code_patterns: List[str]  # Code patterns to look for
    confidence_boost: float = 0.0  # Extra confidence if found


# Common framework signatures for detection
FRAMEWORK_SIGNATURES: List[FrameworkSignature] = [
    # Python Web Frameworks
    FrameworkSignature(
        name="FastAPI",
        category="web",
        file_patterns=["main.py", "app.py", "api/", "routes/"],
        import_patterns=[r"from fastapi", r"import fastapi", r"from starlette"],
        code_patterns=[r"@app\.(get|post|put|delete|patch)", r"APIRouter", r"Depends\("],
        confidence_boost=0.1
    ),
    FrameworkSignature(
        name="Django",
        category="web",
        file_patterns=["views.py", "models.py", "urls.py", "settings.py", "admin.py"],
        import_patterns=[r"from django", r"import django"],
        code_patterns=[r"class.*\(models\.Model\)", r"@login_required", r"HttpResponse"],
        confidence_boost=0.1
    ),
    FrameworkSignature(
        name="Flask",
        category="web",
        file_patterns=["app.py", "views.py", "routes.py"],
        import_patterns=[r"from flask", r"import flask"],
        code_patterns=[r"@app\.route", r"Flask\(__name__\)", r"render_template"],
        confidence_boost=0.1
    ),
    
    # Testing Frameworks
    FrameworkSignature(
        name="pytest",
        category="testing",
        file_patterns=["test_", "_test.py", "conftest.py", "tests/"],
        import_patterns=[r"import pytest", r"from pytest"],
        code_patterns=[r"@pytest\.(fixture|mark)", r"def test_", r"assert "],
        confidence_boost=0.05
    ),
    FrameworkSignature(
        name="unittest",
        category="testing",
        file_patterns=["test_", "_test.py"],
        import_patterns=[r"import unittest", r"from unittest"],
        code_patterns=[r"class.*\(unittest\.TestCase\)", r"self\.assert"],
        confidence_boost=0.05
    ),
    
    # ORM/Database
    FrameworkSignature(
        name="SQLAlchemy",
        category="orm",
        file_patterns=["models.py", "database.py", "db.py"],
        import_patterns=[r"from sqlalchemy", r"import sqlalchemy"],
        code_patterns=[r"Column\(", r"relationship\(", r"Base\.metadata", r"Session"],
        confidence_boost=0.1
    ),
    FrameworkSignature(
        name="Pydantic",
        category="validation",
        file_patterns=["schemas.py", "models.py", "schema.py"],
        import_patterns=[r"from pydantic", r"import pydantic"],
        code_patterns=[r"class.*\(BaseModel\)", r"Field\(", r"validator"],
        confidence_boost=0.05
    ),
    
    # Async/Concurrency
    FrameworkSignature(
        name="asyncio",
        category="async",
        file_patterns=[],
        import_patterns=[r"import asyncio", r"from asyncio"],
        code_patterns=[r"async def", r"await ", r"asyncio\.run", r"asyncio\.gather"],
        confidence_boost=0.05
    ),
    FrameworkSignature(
        name="Celery",
        category="task_queue",
        file_patterns=["tasks.py", "celery.py"],
        import_patterns=[r"from celery", r"import celery"],
        code_patterns=[r"@celery\.task", r"@shared_task", r"\.delay\("],
        confidence_boost=0.1
    ),
    
    # HTTP/API Clients
    FrameworkSignature(
        name="httpx",
        category="http_client",
        file_patterns=[],
        import_patterns=[r"import httpx", r"from httpx"],
        code_patterns=[r"httpx\.(get|post|put|delete)", r"AsyncClient"],
        confidence_boost=0.05
    ),
    FrameworkSignature(
        name="requests",
        category="http_client",
        file_patterns=[],
        import_patterns=[r"import requests", r"from requests"],
        code_patterns=[r"requests\.(get|post|put|delete)"],
        confidence_boost=0.05
    ),
    
    # LangChain/AI
    FrameworkSignature(
        name="LangChain",
        category="ai",
        file_patterns=["chains/", "agents/", "prompts/"],
        import_patterns=[r"from langchain", r"import langchain"],
        code_patterns=[r"LLMChain", r"PromptTemplate", r"ChatOpenAI"],
        confidence_boost=0.1
    ),
    FrameworkSignature(
        name="LangGraph",
        category="ai",
        file_patterns=["workflow", "graph"],
        import_patterns=[r"from langgraph", r"import langgraph"],
        code_patterns=[r"StateGraph", r"add_node", r"add_edge"],
        confidence_boost=0.1
    ),
    
    # Temporal
    FrameworkSignature(
        name="Temporal",
        category="workflow",
        file_patterns=["workflows/", "activities/", "worker"],
        import_patterns=[r"from temporalio", r"import temporalio"],
        code_patterns=[r"@workflow\.defn", r"@activity\.defn", r"workflow\.run"],
        confidence_boost=0.1
    ),
]


# Code pattern signatures
CODE_PATTERN_SIGNATURES = [
    ("async_await", r"async\s+def|await\s+", "Async/await patterns"),
    ("decorators", r"@\w+[\.\w]*\s*(\(|$)", "Decorator usage"),
    ("type_hints", r":\s*(str|int|float|bool|List|Dict|Optional|Any|Tuple)", "Type hints"),
    ("context_managers", r"with\s+\w+.*:", "Context managers"),
    ("comprehensions", r"\[.*for.*in.*\]|\{.*for.*in.*\}", "List/dict comprehensions"),
    ("dataclasses", r"@dataclass", "Dataclass usage"),
    ("exception_handling", r"try:|except\s+\w+:|raise\s+\w+", "Exception handling"),
    ("logging", r"logger\.|logging\.", "Logging statements"),
    ("dependency_injection", r"Depends\(|@inject|Inject\[", "Dependency injection"),
]


# Language detection by file extension
LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sql": "sql",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
}


# ============================================================================
# CONTEXT ANALYZER NODE IMPLEMENTATION
# ============================================================================

class ContextAnalyzerNode(BaseReviewGenerationNode):
    """
    Node 1: Analyze context pack for technical patterns and complexity.
    
    This node extracts:
    - Technical metadata (frameworks, patterns, test coverage)
    - Context classification (seed symbols vs related)
    - Review focus areas based on code analysis
    - Complexity estimation
    - Technical summary for LLM prompt
    """

    def __init__(self, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(
            name="context_analyzer",
            timeout_seconds=30.0,
            circuit_breaker=circuit_breaker,
            max_retries=2
        )
        self._framework_signatures = FRAMEWORK_SIGNATURES
        self._pattern_signatures = CODE_PATTERN_SIGNATURES
        
    async def _execute_node_logic(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze context pack for technical insights.
        
        Args:
            state: Workflow state containing context_pack
            
        Returns:
            Dict with analyzed_context key containing AnalyzedContext
        """
        self.logger.info("Analyzing context pack for technical patterns")

        context_pack = state["context_pack"]
        context_items = context_pack.get("context_items", [])
        patches = state.get("patches", [])

        # Extract all code content for analysis
        all_code_content = self._extract_code_content(context_items)
        all_file_paths = self._extract_file_paths(context_items, patches)

        # Detect frameworks and libraries
        frameworks_detected = self._detect_frameworks(all_code_content, all_file_paths)

        # Detect code patterns
        patterns_detected = self._detect_code_patterns(all_code_content, all_file_paths)

        # Analyze languages
        languages = self._analyze_languages(all_file_paths)

        # Classify context items
        seed_count, related_count = self._classify_context_items(context_items)

        # Count test files
        test_file_count = self._count_test_files(all_file_paths)

        # Identify focus areas
        focus_areas = self._identify_focus_areas(
            context_items, patches, frameworks_detected, patterns_detected
        )

        # Calculate complexity
        total_chars = sum(len(item.get("code_snippet", "") or item.get("snippet", "")) 
                        for item in context_items)
        complexity = self._estimate_complexity(
            len(context_items), total_chars, len(patches), 
            frameworks_detected, patterns_detected
        )

        # Build technical summary
        technical_summary = self._build_technical_summary(
            languages, frameworks_detected, patterns_detected,
            seed_count, related_count, test_file_count, complexity
        )

        # Build AnalyzedContext
        analyzed_context = AnalyzedContext(
            frameworks_detected=frameworks_detected,
            patterns_detected=patterns_detected,
            languages=languages,
            seed_symbol_count=seed_count,
            related_symbol_count=related_count,
            test_file_count=test_file_count,
            focus_areas=focus_areas,
            total_context_chars=total_chars,
            total_context_items=len(context_items),
            estimated_complexity=complexity,
            technical_summary=technical_summary
        )

        self.logger.info(
            f"Context analysis complete: {len(frameworks_detected)} frameworks, "
            f"{len(patterns_detected)} patterns, {len(focus_areas)} focus areas, "
            f"complexity={complexity}"
        )

        return {"analyzed_context": analyzed_context.model_dump()}

    def _get_required_state_keys(self) -> List[str]:
        return ["context_pack"]

    def _get_state_type_requirements(self) -> Dict[str, type]:
        return {"context_pack": dict}

    # ========================================================================
    # EXTRACTION HELPERS
    # ========================================================================

    def _extract_code_content(self, context_items: List[Dict[str, Any]]) -> str:
        """Extract all code content from context items."""
        code_parts = []
        for item in context_items:
            snippet = item.get("code_snippet") or item.get("snippet") or ""
            if snippet:
                code_parts.append(snippet)
        return "\n".join(code_parts)

    def _extract_file_paths(
        self, 
        context_items: List[Dict[str, Any]], 
        patches: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract all unique file paths."""
        paths = set()
        for item in context_items:
            path = item.get("file_path", "")
            if path:
                paths.add(path)
        for patch in patches:
            path = patch.get("file_path", "")
            if path:
                paths.add(path)
        return list(paths)

    # ========================================================================
    # FRAMEWORK DETECTION
    # ========================================================================

    def _detect_frameworks(
        self, 
        code_content: str, 
        file_paths: List[str]
    ) -> List[TechnicalInsight]:
        """Detect frameworks and libraries used in the code."""
        detected = []
        file_paths_str = " ".join(file_paths)

        for sig in self._framework_signatures:
            confidence = 0.0
            matched_files = []

            # Check file patterns
            for pattern in sig.file_patterns:
                for path in file_paths:
                    if pattern.lower() in path.lower():
                        confidence += 0.2
                        matched_files.append(path)
                        break

            # Check import patterns
            for pattern in sig.import_patterns:
                if re.search(pattern, code_content, re.IGNORECASE):
                    confidence += 0.4
                    break

            # Check code patterns
            for pattern in sig.code_patterns:
                if re.search(pattern, code_content):
                    confidence += 0.3
                    break

            # Apply confidence boost
            confidence += sig.confidence_boost

            # Cap confidence at 1.0
            confidence = min(confidence, 1.0)

            # Add if confidence is high enough
            if confidence >= 0.4:
                detected.append(TechnicalInsight(
                    insight_type="framework",
                    name=sig.name,
                    confidence=round(confidence, 2),
                    files=list(set(matched_files))[:5]  # Limit to 5 files
                ))

        # Sort by confidence
        detected.sort(key=lambda x: x.confidence, reverse=True)
        return detected[:10]  # Return top 10

    # ========================================================================
    # PATTERN DETECTION
    # ========================================================================

    def _detect_code_patterns(
        self, 
        code_content: str, 
        file_paths: List[str]
    ) -> List[TechnicalInsight]:
        """Detect code patterns in the context."""
        detected = []

        for pattern_name, pattern_regex, description in self._pattern_signatures:
            matches = re.findall(pattern_regex, code_content)
            if matches:
                # Calculate confidence based on match count
                match_count = len(matches)
                if match_count >= 10:
                    confidence = 1.0
                elif match_count >= 5:
                    confidence = 0.8
                elif match_count >= 2:
                    confidence = 0.6
                else:
                    confidence = 0.4

                detected.append(TechnicalInsight(
                    insight_type="pattern",
                    name=pattern_name,
                    confidence=confidence,
                    files=[]  # Patterns are detected across all files
                ))

        # Sort by confidence
        detected.sort(key=lambda x: x.confidence, reverse=True)
        return detected[:10]

    # ========================================================================
    # LANGUAGE ANALYSIS
    # ========================================================================

    def _analyze_languages(self, file_paths: List[str]) -> Dict[str, int]:
        """Analyze languages based on file extensions."""
        language_counts: Dict[str, int] = defaultdict(int)

        for path in file_paths:
            # Get extension
            ext = ""
            if "." in path:
                ext = "." + path.rsplit(".", 1)[-1].lower()

            language = LANGUAGE_EXTENSIONS.get(ext, "other")
            language_counts[language] += 1

        return dict(language_counts)

    # ========================================================================
    # CONTEXT CLASSIFICATION
    # ========================================================================

    def _classify_context_items(
        self, 
        context_items: List[Dict[str, Any]]
    ) -> Tuple[int, int]:
        """Classify context items into seed symbols and related."""
        seed_count = 0
        related_count = 0

        for item in context_items:
            # Check various ways an item might be marked as seed
            is_seed = (
                item.get("is_seed_symbol", False) or
                item.get("item_type") == "changed_symbol" or
                item.get("source") == "seed"
            )

            if is_seed:
                seed_count += 1
            else:
                related_count += 1

        return seed_count, related_count

    def _count_test_files(self, file_paths: List[str]) -> int:
        """Count test files in the context."""
        test_count = 0
        test_patterns = ["test_", "_test.", "tests/", "test/", "spec_", "_spec."]

        for path in file_paths:
            path_lower = path.lower()
            if any(pattern in path_lower for pattern in test_patterns):
                test_count += 1

        return test_count

    # ========================================================================
    # FOCUS AREA IDENTIFICATION
    # ========================================================================

    def _identify_focus_areas(
        self,
        context_items: List[Dict[str, Any]],
        patches: List[Dict[str, Any]],
        frameworks: List[TechnicalInsight],
        patterns: List[TechnicalInsight]
    ) -> List[ReviewFocusArea]:
        """Identify areas that should be focused on during review."""
        focus_areas = []

        # Get changed file paths
        changed_files = {p.get("file_path", "") for p in patches}
        
        # Check for security-sensitive files
        security_keywords = ["auth", "login", "password", "token", "secret", "crypt", 
                          "security", "permission", "credential", "oauth", "jwt"]
        security_files = []
        for path in changed_files:
            if any(kw in path.lower() for kw in security_keywords):
                security_files.append(path)
        
        if security_files:
            focus_areas.append(ReviewFocusArea(
                area="Security",
                priority=1,
                reason="Changes involve security-sensitive files (authentication, credentials, etc.)",
                file_paths=security_files[:5]
            ))

        # Check for API/endpoint changes
        api_keywords = ["api/", "routes/", "endpoints/", "views/", "controller"]
        api_files = []
        for path in changed_files:
            if any(kw in path.lower() for kw in api_keywords):
                api_files.append(path)
        
        if api_files:
            focus_areas.append(ReviewFocusArea(
                area="API Changes",
                priority=2,
                reason="Changes to API endpoints may affect external consumers",
                file_paths=api_files[:5]
            ))

        # Check for database/model changes
        db_keywords = ["models", "migrations", "database", "schema", "repository"]
        db_files = []
        for path in changed_files:
            if any(kw in path.lower() for kw in db_keywords):
                db_files.append(path)
        
        if db_files:
            focus_areas.append(ReviewFocusArea(
                area="Data Layer",
                priority=2,
                reason="Changes to data models or database may require migration considerations",
                file_paths=db_files[:5]
            ))

        # Check for test file changes
        test_files = []
        for path in changed_files:
            if "test" in path.lower():
                test_files.append(path)
        
        if test_files:
            focus_areas.append(ReviewFocusArea(
                area="Test Coverage",
                priority=3,
                reason="Test file changes - verify test coverage is adequate",
                file_paths=test_files[:5]
            ))
        elif changed_files and not test_files:
            # No test changes but code changes - flag for test review
            focus_areas.append(ReviewFocusArea(
                area="Missing Tests",
                priority=2,
                reason="Code changes without corresponding test updates - consider adding tests",
                file_paths=list(changed_files)[:5]
            ))

        # Check for configuration changes
        config_keywords = ["config", "settings", ".env", ".yaml", ".yml", ".json", ".toml"]
        config_files = []
        for path in changed_files:
            if any(kw in path.lower() for kw in config_keywords):
                config_files.append(path)
        
        if config_files:
            focus_areas.append(ReviewFocusArea(
                area="Configuration",
                priority=3,
                reason="Configuration changes may affect deployment or runtime behavior",
                file_paths=config_files[:5]
            ))

        # Check for async patterns (concurrency review needed)
        async_pattern = next((p for p in patterns if p.name == "async_await"), None)
        if async_pattern and async_pattern.confidence >= 0.6:
            focus_areas.append(ReviewFocusArea(
                area="Concurrency",
                priority=2,
                reason="Async/await patterns detected - review for race conditions and proper await usage",
                file_paths=[]
            ))

        # Check for error handling
        exception_pattern = next((p for p in patterns if p.name == "exception_handling"), None)
        if not exception_pattern or exception_pattern.confidence < 0.4:
            focus_areas.append(ReviewFocusArea(
                area="Error Handling",
                priority=3,
                reason="Limited exception handling detected - consider adding error handling",
                file_paths=[]
            ))

        # Sort by priority and limit to top 5
        focus_areas.sort(key=lambda x: x.priority)
        return focus_areas[:5]

    # ========================================================================
    # COMPLEXITY ESTIMATION
    # ========================================================================

    def _estimate_complexity(
        self,
        item_count: int,
        total_chars: int,
        patch_count: int,
        frameworks: List[TechnicalInsight],
        patterns: List[TechnicalInsight]
    ) -> str:
        """Estimate review complexity based on various factors."""
        complexity_score = 0

        # Item count factor
        if item_count > 30:
            complexity_score += 3
        elif item_count > 15:
            complexity_score += 2
        elif item_count > 5:
            complexity_score += 1

        # Character count factor
        if total_chars > 50000:
            complexity_score += 3
        elif total_chars > 20000:
            complexity_score += 2
        elif total_chars > 5000:
            complexity_score += 1

        # Patch count factor
        if patch_count > 20:
            complexity_score += 3
        elif patch_count > 10:
            complexity_score += 2
        elif patch_count > 3:
            complexity_score += 1

        # Framework diversity factor
        if len(frameworks) > 5:
            complexity_score += 2
        elif len(frameworks) > 2:
            complexity_score += 1

        # Pattern diversity factor
        if len(patterns) > 7:
            complexity_score += 2
        elif len(patterns) > 3:
            complexity_score += 1

        # Map score to complexity level
        if complexity_score >= 8:
            return "high"
        elif complexity_score >= 4:
            return "medium"
        else:
            return "low"

    # ========================================================================
    # TECHNICAL SUMMARY GENERATION
    # ========================================================================

    def _build_technical_summary(
        self,
        languages: Dict[str, int],
        frameworks: List[TechnicalInsight],
        patterns: List[TechnicalInsight],
        seed_count: int,
        related_count: int,
        test_count: int,
        complexity: str
    ) -> str:
        """Build a human-readable technical summary for the LLM prompt."""
        parts = []

        # Language summary
        if languages:
            primary_langs = sorted(languages.items(), key=lambda x: x[1], reverse=True)[:3]
            lang_str = ", ".join(f"{lang} ({count} files)" for lang, count in primary_langs)
            parts.append(f"Primary languages: {lang_str}")

        # Framework summary
        if frameworks:
            high_conf_frameworks = [f.name for f in frameworks if f.confidence >= 0.6]
            if high_conf_frameworks:
                parts.append(f"Frameworks detected: {', '.join(high_conf_frameworks)}")

        # Pattern summary
        if patterns:
            high_conf_patterns = [p.name.replace("_", " ") for p in patterns if p.confidence >= 0.6]
            if high_conf_patterns:
                parts.append(f"Code patterns: {', '.join(high_conf_patterns)}")

        # Context coverage
        parts.append(f"Context coverage: {seed_count} changed symbols, {related_count} related symbols")

        # Test coverage
        if test_count > 0:
            parts.append(f"Test files in context: {test_count}")
        else:
            parts.append("No test files in context")

        # Complexity
        parts.append(f"Estimated complexity: {complexity}")

        return ". ".join(parts) + "."

    # ========================================================================
    # GRACEFUL DEGRADATION
    # ========================================================================

    async def _attempt_graceful_degradation(
        self,
        state: Dict[str, Any],
        error: Exception,
        metrics: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Provide fallback analysis when full analysis fails.
        """
        self.logger.warning(f"Using graceful degradation for context analysis: {error}")

        try:
            context_pack = state.get("context_pack", {})
            context_items = context_pack.get("context_items", [])

            # Basic fallback analysis
            total_items = len(context_items)
            total_chars = sum(
                len(item.get("code_snippet", "") or item.get("snippet", "")) 
                for item in context_items
            )

            fallback_context = AnalyzedContext(
                frameworks_detected=[],
                patterns_detected=[],
                languages={"unknown": total_items},
                seed_symbol_count=0,
                related_symbol_count=total_items,
                test_file_count=0,
                focus_areas=[],
                total_context_chars=total_chars,
                total_context_items=total_items,
                estimated_complexity="medium",
                technical_summary=f"Context contains {total_items} items ({total_chars} characters). Analysis was limited due to processing constraints."
            )

            return {"analyzed_context": fallback_context.model_dump()}

        except Exception as fallback_error:
            self.logger.error(f"Graceful degradation also failed: {fallback_error}")
            return None
