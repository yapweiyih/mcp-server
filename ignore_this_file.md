# Tasks

- (1) create python function using bq client to retrieve data based on query, you should design function input param in a way that can be easily extend to MCP server tool later
- sample data in er_*.json
- database config is in .env_dev
- Support the following type of query efficiently
  - retrieve ER based on input email, assigned_ce_email=weiyih@google.com
  - retrieve ER based on input year, year/month, based on created_at date
  - return result only need to include the following fields:
    - er_name
    - account_name
    - account_sub_region
    - assigned_ce_email
    - details

- Test every function locally with different input param to ensure it is working
- (2) Once local test pass, deploy the function as MCP server tools onto cloud run
  - First run a local mcp server tool to ensure it is working
  - Once pass all local test, deploy to cloudrun
- Next build an adk agent (use adk_python) that use this mcp tools, to answer user query
  - Create different prompt to ensure agent return the correct answer.
- You should complete this task autonomously, ensure all valid use cases and test cases are covered
- Commit your code for every logical point that has been tested working with clear message, and move on to next features.
- create a Makefile to easily run the above test
- Before you complete the task, do a final validation to see if you can improve or if there is any bug.