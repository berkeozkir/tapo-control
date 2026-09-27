#include <windows.h>
#include <shellapi.h>

#include <filesystem>
#include <string>

namespace fs = std::filesystem;

static std::wstring quote_argument(const std::wstring& value) {
    std::wstring quoted = L"\"";
    unsigned backslashes = 0;

    for (wchar_t ch : value) {
        if (ch == L'\\') {
            ++backslashes;
            continue;
        }
        if (ch == L'\"') {
            quoted.append(backslashes * 2 + 1, L'\\');
            quoted += ch;
            backslashes = 0;
            continue;
        }
        quoted.append(backslashes, L'\\');
        backslashes = 0;
        quoted += ch;
    }
    quoted.append(backslashes * 2, L'\\');
    quoted += L'\"';
    return quoted;
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    wchar_t executable_buffer[32768] = {};
    const DWORD length = GetModuleFileNameW(nullptr, executable_buffer, 32768);
    if (length == 0 || length == 32768) {
        MessageBoxW(nullptr, L"Luma could not locate its installation folder.", L"Luma", MB_OK | MB_ICONERROR);
        return 1;
    }

    const fs::path executable_path(executable_buffer);
    const fs::path project_dir = executable_path.parent_path().parent_path().parent_path();
    const fs::path python_path = project_dir / L".venv" / L"Scripts" / L"pythonw.exe";
    const fs::path script_path = project_dir / L"tray_app.py";

    if (!fs::exists(python_path) || !fs::exists(script_path)) {
        const std::wstring message = L"Luma's application files are missing from:\n" + project_dir.wstring();
        MessageBoxW(nullptr, message.c_str(), L"Luma", MB_OK | MB_ICONERROR);
        return 2;
    }

    int argument_count = 0;
    LPWSTR* arguments = CommandLineToArgvW(GetCommandLineW(), &argument_count);
    std::wstring command_line = quote_argument(python_path.wstring()) + L" " + quote_argument(script_path.wstring());
    for (int index = 1; arguments && index < argument_count; ++index) {
        command_line += L" " + quote_argument(arguments[index]);
    }
    if (arguments) {
        LocalFree(arguments);
    }

    STARTUPINFOW startup_info{};
    startup_info.cb = sizeof(startup_info);
    PROCESS_INFORMATION process_info{};
    std::wstring working_directory = project_dir.wstring();

    const BOOL started = CreateProcessW(
        python_path.c_str(),
        command_line.data(),
        nullptr,
        nullptr,
        FALSE,
        CREATE_NO_WINDOW,
        nullptr,
        working_directory.c_str(),
        &startup_info,
        &process_info
    );

    if (!started) {
        const std::wstring message = L"Luma could not start (Windows error " + std::to_wstring(GetLastError()) + L").";
        MessageBoxW(nullptr, message.c_str(), L"Luma", MB_OK | MB_ICONERROR);
        return 3;
    }

    CloseHandle(process_info.hThread);
    CloseHandle(process_info.hProcess);
    return 0;
}
