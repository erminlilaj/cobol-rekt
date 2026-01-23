# Recommended Fix: Use Docker (Easiest)
Since we have updated the `Dockerfile` to handle the build process, this is the most reliable way to avoid local environment issues.

1.  **Pull the latest changes** to your Windows machine (to get the new `Dockerfile`).
2.  Open PowerShell in the project root.
3.  Run:
    ```powershell
    docker build -t cobol-rekt .
    ```
4.  Once built, run the container:
    ```powershell
    docker run -p 7070:7070 cobol-rekt
    ```

---

# Alternative: Fix Local Maven Build (Manual)
If you cannot use Docker and must build directly on Windows, follow these steps to clear the corrupted cache.

## Step 1: Clean Local Repository
Run this command to delete the conflicting artifacts:
```powershell
rmdir /s /q "%USERPROFILE%\.m2\repository\org\eclipse\lsp\cobol"
```

## Step 2: Force Update
Run this from the project root:
```powershell
mvn -U clean install -DskipTests
```

## Step 3: Verify
If it still fails, checking the dependency tree is your best debugging tool:
```powershell
cd server\common
mvn dependency:tree -Dverbose -Dincludes=org.eclipse.lsp.cobol
```
