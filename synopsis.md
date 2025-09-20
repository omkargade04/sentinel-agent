# AI Code Reviewer: System Implementation Details

## 1. Introduction

This document provides a detailed overview of the system architecture and implementation for the AI Code Reviewer. The system is designed to provide automated, context-aware reviews of pull requests in GitHub. It works in two main phases: an initial setup and indexing phase, and an ongoing PR review processing phase.

The architecture is built on a modern, scalable stack, leveraging microservices, workflow orchestration, and advanced AI techniques like Retrieval-Augmented Generation (RAG) to provide high-quality code reviews.

## 2. Phase 1: Context/Repo Setup

This phase is initiated when a user installs the AI Code Reviewer GitHub App and grants it access to their repositories. The goal of this phase is to build a comprehensive, searchable knowledge base of the codebase.

![Context/Repo Setup Phase](https://user-images.githubusercontent.com/12345/67890.png)  <!-- Placeholder for the diagram -->

### 2.1. Onboarding Flow

1.  **GitHub App Installation**: A user installs the GitHub App, initiating the onboarding process.
2.  **Authentication & Authorization**: The user authenticates and authorizes the app to access selected repositories.
3.  **Installation ID Storage**: The system receives an `installation_id` from GitHub, which is securely stored in the primary PostgreSQL database, linked to the user/customer account.

### 2.2. Repository Indexing

<img width="1345" height="305" alt="image" src="https://github.com/user-attachments/assets/7d6aaced-fea8-43c4-b5c7-9031aa7c639b" />

Once a repository is selected, a durable, long-running indexing process is started, orchestrated by Temporal.

1.  **Clone Repository**: The latest version of the repository is cloned to a temporary worker environment.
2.  **AST Parsing**: The source code is parsed into Abstract Syntax Trees (ASTs) using a parser like Tree-sitter. This provides a structured representation of the code.
3.  **Symbol Extraction**: From the AST, key code entities (symbols) like functions, classes, methods, and variables are extracted. Information about their relationships (e.g., function calls, class inheritance) is used to build a code graph.
4.  **Docstring Generation & Embeddings**: For each symbol, a concise summary or docstring is generated. These summaries are then converted into vector embeddings using a pre-trained language model.
5.  **Data Storage**:
    *   The code graph (symbols and their relationships) is stored in the primary **PostgreSQL** database.
    *   The vector embeddings are stored in **pgvector**, a PostgreSQL extension that enables efficient similarity search.

This indexing process creates a rich, multi-faceted representation of the codebase, enabling both semantic (meaning-based) and lexical (keyword-based) search during the PR review phase.

## 3. Phase 2: PR Review Processing

<img width="1367" height="537" alt="image" src="https://github.com/user-attachments/assets/13f0ff2e-d35c-4bab-952d-4fbe4520ae11" />

This phase is triggered whenever a user opens a new pull request or pushes new commits to an existing one. The system uses the indexed knowledge of the repository to provide a detailed, line-by-line review.

### 3.1. Workflow

1.  **Webhook Reception**: GitHub sends a `pull_request` webhook to the system's **API Gateway**, which is a **FastAPI** application.
2.  **Workflow Orchestration**: The FastAPI server acts as a thin gateway, validating the webhook and then handing off the review task to **Temporal**. Temporal orchestrates the entire review process as a durable workflow, which is resilient to failures.
3.  **Caching**: Before starting the process, **Redis** is checked to see if an identical diff has been processed recently. If so, the cached review is returned immediately to save computational resources.
4.  **Worker Execution**: A Temporal worker picks up the task and executes the following steps:
    a. **Fetch PR Diff**: The worker uses the GitHub API to fetch the diff of the pull request.
    b. **Map Diff to Symbols**: The changes in the diff are mapped to the symbols in the code graph that was created during the indexing phase. This identifies which parts of the codebase are being modified.
    c. **Context Retrieval (RAG)**: This is the core of the review process. The system builds a "Context Pack" to send to the LLM. This is done using a hybrid retrieval approach:
        *   **Semantic Retrieval**: Using the embeddings in **pgvector**, a semantic search is performed to find symbols and code snippets that are semantically related to the changes in the PR, even if they don't share keywords.
        *   **Lexical Retrieval**: A traditional keyword-based search is also performed to find relevant documentation, comments, and other textual information.
        *   **Agentic Follow-ups**: The system may perform additional queries based on the initial retrieval results to build a more complete picture of the context.
    d. **Assemble LLM Query**: The retrieved context, the PR diff, and a carefully crafted prompt are assembled into a query for the Large Language Model (LLM).
5.  **LLM Review Generation**: The query is sent to a powerful LLM, which generates a code review with suggestions, potential bugs, and other feedback.
6.  **Caching and Storage**: The generated review is cached in **Redis** for future use and stored permanently in the **PostgreSQL** database for auditing and analytics.
7.  **Publish Review**: The review is posted as a comment on the pull request in GitHub.

## 4. Technology Stack

| Component                | Technology                               | Role                                                                                                                             |
| ------------------------ | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **Backend**              | FastAPI (Python)                         | Serves as the API Gateway for GitHub webhooks and REST APIs.                                                                     |
| **Workflow Orchestrator**| Temporal                                 | Manages long-running, reliable workflows for repository indexing and PR reviews. Provides retries, observability, and state management. |
| **Primary Database**     | PostgreSQL                               | Stores all primary application data, including user accounts, repository information, code graph (symbols), and review history.     |
| **Vector Database**      | pgvector                                 | A PostgreSQL extension that stores vector embeddings of code for semantic search.                                              |
| **Caching**              | Redis                                    | Used for caching responses for identical diffs and other frequently accessed data to improve performance.                           |
| **Code Parsing**         | Tree-sitter                              | Parses source code into Abstract Syntax Trees (ASTs) for symbol extraction and structural analysis.                              |
| **AI/ML**                | LLMs (e.g., GPT-4, Claude)               | Generates the code reviews based on the context provided by the RAG system.                                                      |
| **Deployment**           | Docker, Kubernetes                       | The system is containerized and can be deployed on any cloud platform using Kubernetes for scalability and resilience.          |

## 5. Architectural Benefits

*   **Scalability**: The microservices-based architecture, combined with the use of a workflow orchestrator and a message queue, allows the system to scale horizontally to handle a large number of repositories and pull requests.
*   **Reliability**: Temporal's durable workflows ensure that indexing and review processes are resilient to failures and can be resumed automatically.
*   **Context-Aware Reviews**: The use of RAG with a hybrid retrieval strategy allows the system to provide highly context-aware reviews that understand the nuances of the codebase.
*   **Observability**: Temporal provides detailed logs and traces for each workflow, making it easy to monitor and debug the system.
*   **Extensibility**: The modular architecture makes it easy to add support for new programming languages, integrate with other developer tools, or swap out the LLM for a different model.
