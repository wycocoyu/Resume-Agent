# 数据库表结构参考 (PostgreSQL / BetterAuth)

- **说明**：本文档记录系统在启用 PostgreSQL + BetterAuth 统一认证后的完整 15 张表结构、索引与外键约束（本地开发默认支持 SQLite 开箱即用）。
- **身份锚点**:BetterAuth `"user".id`(32 位字符串);业务表 `user_id` 均为 `character varying`,**无 users 表**(2026-07-19 P5 已 DROP)
- **schema 管理**:bootstrap = `npx auth migrate`(BetterAuth 4 表)+ `python backend/create_tables.py`(业务表);alembic 已于 2026-07-19 移除
- **表分组**:
  - BetterAuth 认证(4):`user` / `account` / `session` / `verification`
  - 权益与身份扩展(1):`better_auth_entitlements`(role / pdf_download_count,LEFT JOIN "user" 使用)
  - 核心业务(3):`resumes` / `resume_embeddings` / `score_results`
  - Agent 会话(2):`agent_conversations` / `agent_messages`
  - 运维观测(3):`api_request_logs` / `api_error_logs` / `api_trace_spans`
  - 其它(2):`members` / `permission_audit_logs`

---

共 15 张表: account, agent_conversations, agent_messages, api_error_logs, api_request_logs, api_trace_spans, better_auth_entitlements, members, permission_audit_logs, resume_embeddings, resumes, score_results, session, user, verification

## `account`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | text |  |  |
| accountId | text |  |  |
| providerId | text |  |  |
| userId | text |  |  |
| accessToken | text | ✓ |  |
| refreshToken | text | ✓ |  |
| idToken | text | ✓ |  |
| accessTokenExpiresAt | timestamp with time zone | ✓ |  |
| refreshTokenExpiresAt | timestamp with time zone | ✓ |  |
| scope | text | ✓ |  |
| password | text | ✓ |  |
| createdAt | timestamp with time zone |  | CURRENT_TIMESTAMP |
| updatedAt | timestamp with time zone |  |  |

索引:
- `account_pkey`: btree (id)
- `account_userId_idx`: btree ("userId")

外键:
- `account_userId_fkey`: FOREIGN KEY ("userId") REFERENCES "user"(id) ON DELETE CASCADE

## `agent_conversations`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('agent_conversations_id_seq'::re… |
| session_id | character varying(255) |  |  |
| title | character varying(255) |  |  |
| message_count | integer |  |  |
| meta | json | ✓ |  |
| created_at | timestamp with time zone | ✓ | now() |
| updated_at | timestamp with time zone | ✓ | now() |
| last_message_at | timestamp with time zone | ✓ |  |
| user_id | character varying(255) | ✓ |  |

索引:
- `agent_conversations_pkey`: btree (id)
- `ix_agent_conversations_id`: btree (id)
- `ix_agent_conversations_session_id`: btree (session_id)
- `ix_agent_conversations_updated_at`: btree (updated_at)
- `ix_agent_conversations_user_id`: btree (user_id)

## `agent_messages`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('agent_messages_id_seq'::regclas… |
| conversation_id | integer |  |  |
| seq | integer |  |  |
| role | character varying(20) |  |  |
| content | text | ✓ |  |
| thought | text | ✓ |  |
| name | character varying(255) | ✓ |  |
| message_hash | character varying(64) | ✓ |  |
| tool_call_id | character varying(255) | ✓ |  |
| tool_calls | json | ✓ |  |
| base64_image | text | ✓ |  |
| created_at | timestamp with time zone | ✓ | now() |

索引:
- `agent_messages_pkey`: btree (id)
- `uq_agent_messages_conversation_seq`: btree (conversation_id, seq)
- `ix_agent_messages_conversation_id`: btree (conversation_id)
- `ix_agent_messages_id`: btree (id)
- `ix_agent_messages_message_hash`: btree (message_hash)
- `ix_agent_messages_tool_call_id`: btree (tool_call_id)

外键:
- `agent_messages_conversation_id_fkey`: FOREIGN KEY (conversation_id) REFERENCES agent_conversations(id) ON DELETE CASCADE

## `api_error_logs`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('api_error_logs_id_seq'::regclas… |
| request_log_id | integer | ✓ |  |
| trace_id | character varying(64) |  |  |
| error_type | character varying(128) | ✓ |  |
| error_message | text |  |  |
| error_stack | text | ✓ |  |
| service | character varying(128) | ✓ |  |
| created_at | timestamp with time zone | ✓ | now() |

索引:
- `api_error_logs_pkey`: btree (id)
- `ix_api_error_logs_created_at`: btree (created_at)
- `ix_api_error_logs_id`: btree (id)
- `ix_api_error_logs_request_log_id`: btree (request_log_id)
- `ix_api_error_logs_trace_id`: btree (trace_id)

外键:
- `api_error_logs_request_log_id_fkey`: FOREIGN KEY (request_log_id) REFERENCES api_request_logs(id) ON DELETE SET NULL

## `api_request_logs`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('api_request_logs_id_seq'::regcl… |
| trace_id | character varying(64) |  |  |
| request_id | character varying(64) |  |  |
| method | character varying(16) |  |  |
| path | character varying(512) |  |  |
| status_code | integer |  |  |
| latency_ms | double precision |  |  |
| ip | character varying(64) | ✓ |  |
| user_agent | character varying(512) | ✓ |  |
| request_size | integer | ✓ |  |
| response_size | integer | ✓ |  |
| created_at | timestamp with time zone | ✓ | now() |
| user_id | character varying(255) | ✓ |  |

索引:
- `api_request_logs_pkey`: btree (id)
- `ix_api_request_logs_created_at`: btree (created_at)
- `ix_api_request_logs_id`: btree (id)
- `ix_api_request_logs_ip`: btree (ip)
- `ix_api_request_logs_path`: btree (path)
- `ix_api_request_logs_request_id`: btree (request_id)
- `ix_api_request_logs_trace_id`: btree (trace_id)
- `ix_api_request_logs_user_id`: btree (user_id)

## `api_trace_spans`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('api_trace_spans_id_seq'::regcla… |
| trace_id | character varying(64) |  |  |
| span_id | character varying(64) |  |  |
| parent_span_id | character varying(64) | ✓ |  |
| span_name | character varying(255) |  |  |
| start_time | timestamp with time zone |  |  |
| end_time | timestamp with time zone |  |  |
| duration_ms | double precision |  |  |
| status | character varying(32) |  | 'ok'::character varying |
| tags | json | ✓ |  |
| created_at | timestamp with time zone | ✓ | now() |

索引:
- `api_trace_spans_pkey`: btree (id)
- `ix_api_trace_spans_created_at`: btree (created_at)
- `ix_api_trace_spans_id`: btree (id)
- `ix_api_trace_spans_parent_span_id`: btree (parent_span_id)
- `ix_api_trace_spans_span_id`: btree (span_id)
- `ix_api_trace_spans_start_time`: btree (start_time)
- `ix_api_trace_spans_trace_id`: btree (trace_id)

## `better_auth_entitlements`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('better_auth_entitlements_id_seq… |
| better_auth_user_id | character varying(255) |  |  |
| email | character varying(255) | ✓ |  |
| name | character varying(255) | ✓ |  |
| image | text | ✓ |  |
| plan | character varying(64) |  | 'free'::character varying |
| credits | integer |  | 0 |
| daily_usage_count | integer |  | 0 |
| last_usage_reset_at | timestamp with time zone | ✓ |  |
| subscription_status | character varying(64) |  | 'free'::character varying |
| provider_customer_id | character varying(255) | ✓ |  |
| provider_subscription_id | character varying(255) | ✓ |  |
| current_period_end | timestamp with time zone | ✓ |  |
| created_at | timestamp with time zone | ✓ | now() |
| updated_at | timestamp with time zone | ✓ | now() |
| role | character varying(32) |  | 'user'::character varying |
| pdf_download_count | integer |  | 0 |

索引:
- `better_auth_entitlements_pkey`: btree (id)
- `ix_better_auth_entitlements_better_auth_user_id`: btree (better_auth_user_id)
- `ix_better_auth_entitlements_email`: btree (email)
- `ix_better_auth_entitlements_id`: btree (id)
- `ix_better_auth_entitlements_plan`: btree (plan)
- `ix_better_auth_entitlements_provider_customer_id`: btree (provider_customer_id)
- `ix_better_auth_entitlements_provider_subscription_id`: btree (provider_subscription_id)
- `ix_better_auth_entitlements_subscription_status`: btree (subscription_status)
- `ix_better_auth_entitlements_updated_at`: btree (updated_at)
- `ix_better_auth_entitlements_role`: btree (role)

## `members`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('members_id_seq'::regclass) |
| name | character varying(128) |  |  |
| email | character varying(255) | ✓ |  |
| position | character varying(128) | ✓ |  |
| team | character varying(128) | ✓ |  |
| status | character varying(32) |  | 'active'::character varying |
| created_at | timestamp with time zone | ✓ | now() |
| updated_at | timestamp with time zone | ✓ | now() |
| user_id | character varying(255) | ✓ |  |

索引:
- `members_pkey`: btree (id)
- `ix_members_email`: btree (email)
- `ix_members_id`: btree (id)
- `ix_members_user_id`: btree (user_id)

## `permission_audit_logs`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('permission_audit_logs_id_seq'::… |
| from_role | character varying(32) | ✓ |  |
| to_role | character varying(32) | ✓ |  |
| action | character varying(128) |  |  |
| created_at | timestamp with time zone | ✓ | now() |
| operator_user_id | character varying(255) | ✓ |  |
| target_user_id | character varying(255) | ✓ |  |

索引:
- `permission_audit_logs_pkey`: btree (id)
- `ix_permission_audit_logs_created_at`: btree (created_at)
- `ix_permission_audit_logs_id`: btree (id)
- `ix_permission_audit_logs_operator_user_id`: btree (operator_user_id)
- `ix_permission_audit_logs_target_user_id`: btree (target_user_id)

## `resume_embeddings`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('resume_embeddings_id_seq'::regc… |
| resume_id | character varying(255) |  |  |
| embedding | json |  |  |
| content_type | character varying(50) |  |  |
| content | text |  |  |
| metadata | json | ✓ |  |
| created_at | timestamp with time zone | ✓ | now() |
| updated_at | timestamp with time zone | ✓ | now() |
| user_id | character varying(255) |  |  |

索引:
- `resume_embeddings_pkey`: btree (id)
- `ix_resume_embeddings_id`: btree (id)
- `ix_resume_embeddings_resume_id`: btree (resume_id)
- `ix_resume_embeddings_user_id`: btree (user_id)

外键:
- `resume_embeddings_resume_id_fkey`: FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE

## `resumes`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | character varying(255) |  |  |
| name | character varying(255) |  |  |
| alias | character varying(255) | ✓ |  |
| data | json |  |  |
| created_at | timestamp with time zone | ✓ | now() |
| updated_at | timestamp with time zone | ✓ | now() |
| user_id | character varying(255) |  |  |

索引:
- `resumes_pkey`: btree (id)
- `ix_resumes_id`: btree (id)
- `ix_resumes_user_id`: btree (user_id)

## `score_results`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | integer |  | nextval('score_results_id_seq'::regclass… |
| resume_id | character varying(255) |  |  |
| jd_text | text |  |  |
| overall_score | double precision |  |  |
| skill_experience_score | double precision |  |  |
| education_score | double precision |  |  |
| project_overall_score | double precision |  |  |
| dimension_reasons | json |  |  |
| created_at | timestamp with time zone | ✓ | now() |
| user_id | character varying(255) |  |  |

索引:
- `score_results_pkey`: btree (id)
- `ix_score_results_id`: btree (id)
- `ix_score_results_resume_id`: btree (resume_id)
- `ix_score_results_user_id`: btree (user_id)

外键:
- `score_results_resume_id_fkey`: FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE

## `session`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | text |  |  |
| expiresAt | timestamp with time zone |  |  |
| token | text |  |  |
| createdAt | timestamp with time zone |  | CURRENT_TIMESTAMP |
| updatedAt | timestamp with time zone |  |  |
| ipAddress | text | ✓ |  |
| userAgent | text | ✓ |  |
| userId | text |  |  |

索引:
- `session_pkey`: btree (id)
- `session_token_key`: btree (token)
- `session_userId_idx`: btree ("userId")

外键:
- `session_userId_fkey`: FOREIGN KEY ("userId") REFERENCES "user"(id) ON DELETE CASCADE

## `user`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | text |  |  |
| name | text |  |  |
| email | text |  |  |
| emailVerified | boolean |  |  |
| image | text | ✓ |  |
| createdAt | timestamp with time zone |  | CURRENT_TIMESTAMP |
| updatedAt | timestamp with time zone |  | CURRENT_TIMESTAMP |

索引:
- `user_email_key`: btree (email)
- `user_pkey`: btree (id)

## `verification`

| 字段 | 类型 | 可空 | 默认值 |
|---|---|---|---|
| id | text |  |  |
| identifier | text |  |  |
| value | text |  |  |
| expiresAt | timestamp with time zone |  |  |
| createdAt | timestamp with time zone |  | CURRENT_TIMESTAMP |
| updatedAt | timestamp with time zone |  | CURRENT_TIMESTAMP |

索引:
- `verification_pkey`: btree (id)
- `verification_identifier_idx`: btree (identifier)

