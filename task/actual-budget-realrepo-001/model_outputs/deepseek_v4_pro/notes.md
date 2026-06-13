\# DeepSeek-V4-Pro notes



Model: DeepSeek-V4-Pro

Input: prd.md only

Prompt: 请阅读当前项目中的 prd.md，并根据 PRD 实现一个完整的 Python 命令行程序

Manual edits: None



Evaluator result:

Total cases: 30

Passed cases: 20

Failed cases: 10

Score: 0.704545

Unit score: 0.5625

System score: 0.785714

Unit-system gap: -0.223214



Main failure pattern:

The implementation requires a category to exist before adding a transaction. In the PRD/rubric, transactions may use categories such as Food or Income directly in several cases. Because the model rejects missing categories, many transaction-related unit cases fail.



Representative error:

Category 'Food' does not exist

Category 'Income' does not exist



Failed cases:

SQU003, SQU004, SQU005, SQU006, SQU011, SQU012, SQU015, SQS001, SQS003, SQS008

