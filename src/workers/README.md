# Temporal Workers Module

## What

The workers module defines Temporal workers that execute workflows and activities. Workers poll task queues, pick up tasks, and execute the registered workflows/activities.

## Why

Workers are essential for:
- **Task Execution**: Execute workflows and activities from task queues
- **Scalability**: Multiple workers can run in parallel
- **Reliability**: Workers automatically handle task distribution
- **Monitoring**: Workers provide execution visibility

## How

### Architecture

```
workers/
├── repo_indexing_worker.py    # Repository indexing worker
└── README.md                 # This file
```

### Key Workers

#### RepoIndexingWorker (`repo_indexing_worker.py`)

**Purpose**: Executes repository indexing workflows and activities.

**Worker Definition**:
```python
async def main():
    client = await Client.connect(
        target_host=settings.TEMPORAL_SERVER_URL,
    )
    worker = Worker(
        client,
        task_queue="repo-indexing-queue",
        workflows=[RepoIndexingWorkflow],
        activities=[
            clone_repo_activity,
            parse_repo_activity,
            persist_metadata_activity,
            persist_kg_activity,
            cleanup_stale_kg_nodes_activity,
            cleanup_repo_activity,
        ],
    )
    await worker.run()
```

### Worker Configuration

**Task Queue**: `repo-indexing-queue`
- Matches workflow task queue
- Workers poll this queue for tasks

**Registered Workflows**:
- `RepoIndexingWorkflow`: Repository indexing orchestration

**Registered Activities**:
- `clone_repo_activity`: Clone repository
- `parse_repo_activity`: Parse repository
- `persist_metadata_activity`: Persist metadata
- `persist_kg_activity`: Persist knowledge graph
- `cleanup_stale_kg_nodes_activity`: Cleanup stale nodes
- `cleanup_repo_activity`: Cleanup repository

### Worker Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│                  Worker Execution Flow                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Connect to Temporal Server                             │
│     client = await Client.connect(server_url)              │
│           ↓                                                 │
│  2. Create Worker                                          │
│     worker = Worker(                                       │
│         client,                                            │
│         task_queue="repo-indexing-queue",                  │
│         workflows=[...],                                   │
│         activities=[...]                                   │
│     )                                                       │
│           ↓                                                 │
│  3. Start Worker                                           │
│     await worker.run()  # Blocks forever                   │
│           ↓                                                 │
│  4. Worker Polls Task Queue                                │
│     ├── Workflow task → Execute workflow                    │
│     ├── Activity task → Execute activity                    │
│     └── Repeat polling...                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Task Distribution

**How Tasks Are Distributed**:
1. API starts workflow → Temporal schedules workflow task
2. Workflow executes → Schedules activity tasks
3. Temporal distributes tasks to available workers
4. Workers poll and pick up tasks
5. Multiple workers can process tasks in parallel

**Load Balancing**:
- Temporal automatically distributes tasks
- Workers compete for tasks (first come, first served)
- No manual task assignment needed

### Worker Lifecycle

**Startup**:
```python
# Connect to Temporal
client = await Client.connect(server_url)

# Create worker
worker = Worker(...)

# Start worker (blocks)
await worker.run()
```

**Shutdown**:
- Worker runs until interrupted (Ctrl+C)
- Graceful shutdown on SIGTERM
- In-flight tasks complete before shutdown

### Multiple Workers

**Horizontal Scaling**:
```bash
# Worker 1
python -m src.workers.repo_indexing_worker

# Worker 2 (different process)
python -m src.workers.repo_indexing_worker

# Worker 3 (different process)
python -m src.workers.repo_indexing_worker
```

**Benefits**:
- Increased throughput
- Fault tolerance (if one worker dies, others continue)
- Load distribution

### Worker Registration

**Workflows**:
- Must match workflow class name
- Workflow methods registered automatically
- Task queue must match workflow task queue

**Activities**:
- Must be decorated with `@activity.defn`
- Function name used as activity type
- Can register same activity multiple times (different queues)

### Error Handling

**Worker-Level Errors**:
- Worker crashes → Temporal reschedules tasks
- Activity failures → Retried per retry policy
- Workflow failures → Workflow marked as failed

**Task Processing**:
- Exceptions in activities → Wrapped in `ActivityError`
- Exceptions in workflows → Workflow fails
- Worker continues processing other tasks

### Monitoring

**Worker Metrics**:
- Tasks processed per second
- Task success/failure rates
- Worker uptime
- Queue depth

**Temporal UI**:
- View worker status
- Monitor task execution
- Debug workflow/activity failures

### Usage

**Running a Worker**:
```bash
# Direct execution
python -m src.workers.repo_indexing_worker

# Or via script
./scripts/start_worker.sh
```

**Docker**:
```dockerfile
CMD ["python", "-m", "src.workers.repo_indexing_worker"]
```

**Systemd Service**:
```ini
[Unit]
Description=Repository Indexing Worker

[Service]
ExecStart=/usr/bin/python -m src.workers.repo_indexing_worker
Restart=always

[Install]
WantedBy=multi-user.target
```

### Configuration

**Environment Variables**:
- `TEMPORAL_SERVER_URL`: Temporal server address
- Database/Neo4j configs (for activities)

**Task Queue**:
- Must match workflow task queue
- Configurable per worker type

### Testing

```python
# Test worker creation
async def test_worker_creation():
    client = await Client.connect("localhost:7233")
    worker = Worker(
        client,
        task_queue="test-queue",
        workflows=[RepoIndexingWorkflow],
        activities=[clone_repo_activity],
    )
    assert worker.task_queue == "test-queue"
    assert len(worker.workflows) == 1
    assert len(worker.activities) == 1

# Test worker execution (integration test)
async def test_worker_execution():
    # Start worker in background
    worker_task = asyncio.create_task(worker.run())
    
    # Start workflow
    handle = await client.start_workflow(...)
    
    # Wait for completion
    result = await handle.result()
    
    # Stop worker
    worker_task.cancel()
```

### Design Decisions

1. **Single Worker File**: One worker per task queue type
2. **Blocking Run**: `worker.run()` blocks forever
3. **Explicit Registration**: All workflows/activities registered explicitly
4. **Task Queue Matching**: Worker queue matches workflow queue

### Dependencies

- **temporalio**: Temporal Python SDK
- **Workflows**: Workflow definitions
- **Activities**: Activity definitions
- **Services**: Business logic (via activities)

### Future Enhancements

- [ ] Worker health checks
- [ ] Graceful shutdown handling
- [ ] Worker metrics/monitoring
- [ ] Dynamic worker scaling
- [ ] Worker configuration via config file
- [ ] Multiple task queues per worker

