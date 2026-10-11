-- Run once in the "jarvis" database as a member of the SQL admin Entra group
-- (Azure portal Query editor or Azure Data Studio, Entra ID auth).
-- Replace <function-app-name> with the functionAppName deployment output.

CREATE USER [<function-app-name>] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [<function-app-name>];
ALTER ROLE db_datawriter ADD MEMBER [<function-app-name>];
ALTER ROLE db_ddladmin  ADD MEMBER [<function-app-name>];   -- remove after schema is created

-- Read-only access for Power BI (an Entra group of report authors):
-- CREATE USER [JARVIS Power BI Readers] FROM EXTERNAL PROVIDER;
-- ALTER ROLE db_datareader ADD MEMBER [JARVIS Power BI Readers];
