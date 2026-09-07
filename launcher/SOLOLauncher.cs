using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new LauncherForm());
    }
}

internal sealed class LauncherForm : Form
{
    private readonly string root;
    private readonly string app;
    private readonly string data;
    private readonly string logFile;
    private readonly int port;
    private readonly Label status;
    private readonly TextBox details;
    private Process server;

    private static string U(string value) { return value; }

    internal LauncherForm()
    {
        root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        app = Path.Combine(root, "app");
        data = Path.Combine(root, "data");
        logFile = Path.Combine(data, "logs", "launcher.log");
        int configuredPort;
        if (!Int32.TryParse(Environment.GetEnvironmentVariable("SOLO_PORT"), out configuredPort) || configuredPort < 1024 || configuredPort > 65535) configuredPort = 8766;
        port = configuredPort;
        Directory.CreateDirectory(Path.Combine(data, "logs"));
        Text = "SOLO";
        Width = 520;
        Height = 390;
        MinimumSize = new Size(460, 330);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(246, 246, 240);
        Font = new Font("Microsoft YaHei UI", 10F);

        var title = new Label();
        title.Text = "SOLO\r\n\u5355\u4eba\u64ad\u5ba2\u5de5\u4f5c\u53f0";
        title.Font = new Font("Microsoft YaHei UI", 18F, FontStyle.Bold);
        title.ForeColor = Color.FromArgb(42, 68, 56);
        title.AutoSize = true;
        title.Location = new Point(28, 22);
        Controls.Add(title);

        status = new Label();
        status.Text = "\u6b63\u5728\u68c0\u67e5\u8fd0\u884c\u73af\u5883...";
        status.AutoSize = true;
        status.Location = new Point(31, 93);
        status.ForeColor = Color.FromArgb(67, 91, 69);
        Controls.Add(status);

        details = new TextBox();
        details.Multiline = true;
        details.ReadOnly = true;
        details.ScrollBars = ScrollBars.Vertical;
        details.BackColor = Color.White;
        details.BorderStyle = BorderStyle.FixedSingle;
        details.Location = new Point(28, 124);
        details.Size = new Size(448, 168);
        details.Font = new Font("Consolas", 9F);
        Controls.Add(details);

        var foot = new Label();
        foot.Text = "\u6838\u5fc3\u73af\u5883\u5c31\u7eea\u540e\u4f1a\u81ea\u52a8\u6253\u5f00\u9ed8\u8ba4\u6d4f\u89c8\u5668\u3002\u8be6\u7ec6\u65e5\u5fd7\uff1adata\\logs\\launcher.log";
        foot.AutoSize = false;
        foot.Width = 448;
        foot.Height = 42;
        foot.Location = new Point(28, 305);
        foot.ForeColor = Color.FromArgb(126, 139, 121);
        foot.Font = new Font("Microsoft YaHei UI", 8.5F);
        Controls.Add(foot);
        Shown += delegate { ThreadPool.QueueUserWorkItem(delegate { StartFlow(); }); };
    }

    private void Add(string line)
    {
        try
        {
            File.AppendAllText(logFile, DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ") + line + Environment.NewLine, Encoding.UTF8);
        }
        catch { }
        if (IsDisposed) return;
        BeginInvoke((Action)delegate
        {
            details.AppendText(line + Environment.NewLine);
        });
    }

    private void SetStatus(string value)
    {
        if (IsDisposed) return;
        BeginInvoke((Action)delegate { status.Text = value; });
    }

    private bool FileOk(string path, long minimum)
    {
        try { return File.Exists(path) && new FileInfo(path).Length >= minimum; }
        catch { return false; }
    }

    private bool CoreFilesPresent()
    {
        string python = Path.Combine(app, ".runtime", "python", "cpython-3.12.10-windows-x86_64-none", "python.exe");
        string[] files = {
            Path.Combine(app, "server.py"),
            Path.Combine(app, "install-portable.ps1"),
            Path.Combine(app, ".venv", "Scripts", "python.exe"),
            Path.Combine(app, ".runtime", "uv", "uv.exe"),
            Path.Combine(app, ".runtime", "ffmpeg", "bin", "ffmpeg.exe"),
            Path.Combine(app, ".runtime", "ffmpeg", "bin", "ffprobe.exe"),
            Path.Combine(app, ".offline", "main-wheels"),
            Path.Combine(app, "engines", "faster-whisper", "base", "model.bin"),
            Path.Combine(app, "engines", "faster-whisper", "base", "config.json"),
            Path.Combine(app, "engines", "faster-whisper", "base", "tokenizer.json"),
            Path.Combine(app, "engines", "faster-whisper", "base", "vocabulary.txt")
        };
        if (!FileOk(python, 50000)) return false;
        foreach (string file in files)
        {
            if (file.EndsWith("main-wheels", StringComparison.OrdinalIgnoreCase))
            {
                if (!Directory.Exists(file)) return false;
            }
            else if (!FileOk(file, 100)) return false;
        }
        return true;
    }

    private int RunPowerShell(string script, string arguments)
    {
        var psi = new ProcessStartInfo();
        psi.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell\\v1.0\\powershell.exe");
        psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\" " + arguments;
        psi.WorkingDirectory = app;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError = true;
        psi.StandardOutputEncoding = Encoding.UTF8;
        psi.StandardErrorEncoding = Encoding.UTF8;
        psi.EnvironmentVariables["SOLO_PORTABLE"] = "1";
        psi.EnvironmentVariables["SOLO_PORT"] = port.ToString();
        psi.EnvironmentVariables["SOLO_DATA_DIR"] = data;
        string ffbin = Path.Combine(app, ".runtime", "ffmpeg", "bin");
        psi.EnvironmentVariables["PATH"] = ffbin + Path.PathSeparator + Environment.GetEnvironmentVariable("PATH");
        var process = new Process();
        process.StartInfo = psi;
        process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Add(e.Data); };
        process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) Add(e.Data); };
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        process.WaitForExit();
        return process.ExitCode;
    }

    private void StartFlow()
    {
        try
        {
            Environment.SetEnvironmentVariable("SOLO_DATA_DIR", data);
            Environment.SetEnvironmentVariable("SOLO_PORT", port.ToString());
            Environment.SetEnvironmentVariable("PYTHONUTF8", "1");
            string ffbin = Path.Combine(app, ".runtime", "ffmpeg", "bin");
            Environment.SetEnvironmentVariable("PATH", ffbin + Path.PathSeparator + Environment.GetEnvironmentVariable("PATH"));
            Add("SOLO Portable v0.1.0-beta.1");
            Add("\u5e94\u7528\u76ee\u5f55: " + app);
            SetStatus("\u6b63\u5728\u68c0\u67e5\u6838\u5fc3\u6587\u4ef6...");
            if (!CoreFilesPresent())
            {
                Add("\u6838\u5fc3\u73af\u5883\u672a\u5b8c\u6210\uff0c\u5f00\u59cb\u79bb\u7ebf\u51c6\u5907\u3002");
                SetStatus("\u9996\u6b21\u542f\u52a8\uff1a\u6b63\u5728\u51c6\u5907 Python / FFmpeg / Whisper...");
                int code = RunPowerShell(Path.Combine(app, "install-portable.ps1"), "-Portable -SkipModels");
                if (code != 0 || !CoreFilesPresent()) throw new Exception("\u4fbf\u643a\u7248\u6838\u5fc3\u73af\u5883\u51c6\u5907\u5931\u8d25\u3002");
            }
            else Add("\u6838\u5fc3\u6587\u4ef6\u5df2\u5b8c\u6574\u3002");
            SetStatus("\u6b63\u5728\u542f\u52a8 SOLO \u5de5\u4f5c\u53f0...");
            if (!WaitHealth(1)) StartServer();
            if (!WaitHealth(30)) throw new Exception("\u7aef\u53e3 8766 \u65e0\u6cd5\u542f\u52a8\uff0c\u8bf7\u67e5\u770b data\\logs\\server-error.log\u3002");
            Add("/health \u68c0\u67e5\u6210\u529f\u3002");
            SetStatus("\u5de5\u4f5c\u53f0\u5df2\u542f\u52a8\uff0c\u6b63\u5728\u6253\u5f00\u6d4f\u89c8\u5668...");
            Process.Start(new ProcessStartInfo("http://127.0.0.1:" + port.ToString()) { UseShellExecute = true });
            SetStatus("SOLO \u5df2\u5c31\u7eea\uff0c\u53ef\u4ee5\u5173\u95ed\u6b64\u7a97\u53e3\u3002");
        }
        catch (Exception ex)
        {
            Add("ERROR: " + ex.ToString());
            SetStatus("SOLO \u542f\u52a8\u5931\u8d25");
            if (!IsDisposed)
                BeginInvoke((Action)delegate { MessageBox.Show(this, "SOLO \u542f\u52a8\u5931\u8d25\r\n\r\n\u6838\u5fc3\u8fd0\u884c\u73af\u5883\u4e0d\u5b8c\u6574\u6216\u7aef\u53e3\u65e0\u6cd5\u542f\u52a8\u3002\r\n\u8be6\u7ec6\u65e5\u5fd7\uff1adata\\logs\\launcher.log", "SOLO", MessageBoxButtons.OK, MessageBoxIcon.Error); });
        }
    }

    private bool WaitHealth(int seconds)
    {
        DateTime end = DateTime.UtcNow.AddSeconds(seconds);
        while (DateTime.UtcNow < end)
        {
            try
            {
                var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port.ToString() + "/health");
                request.Timeout = 1200;
                using (var response = (HttpWebResponse)request.GetResponse())
                using (var stream = response.GetResponseStream())
                using (var reader = new StreamReader(stream))
                {
                    string body = reader.ReadToEnd();
                    if ((int)response.StatusCode == 200 && body.IndexOf("\"status\"", StringComparison.OrdinalIgnoreCase) >= 0 && body.IndexOf("\"ok\"", StringComparison.OrdinalIgnoreCase) >= 0) return true;
                }
            }
            catch { }
            Thread.Sleep(400);
        }
        return false;
    }

    private void StartServer()
    {
        string python = Path.Combine(app, ".venv", "Scripts", "python.exe");
        if (!FileOk(python, 50000)) throw new Exception("\u72ec\u7acb Python \u73af\u5883\u5c1a\u672a\u51c6\u5907\u5b8c\u6210\u3002");
        Directory.CreateDirectory(Path.Combine(data, "logs"));
        var psi = new ProcessStartInfo();
        psi.FileName = python;
        psi.Arguments = "-u \"" + Path.Combine(app, "server.py") + "\"";
        psi.WorkingDirectory = app;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError = true;
        psi.StandardOutputEncoding = Encoding.UTF8;
        psi.StandardErrorEncoding = Encoding.UTF8;
        psi.EnvironmentVariables["SOLO_DATA_DIR"] = data;
        psi.EnvironmentVariables["SOLO_PORT"] = port.ToString();
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        string ffbin = Path.Combine(app, ".runtime", "ffmpeg", "bin");
        psi.EnvironmentVariables["PATH"] = ffbin + Path.PathSeparator + Environment.GetEnvironmentVariable("PATH");
        server = new Process();
        server.StartInfo = psi;
        server.EnableRaisingEvents = true;
        server.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) AppendServer("server.log", e.Data); };
        server.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) AppendServer("server-error.log", e.Data); };
        server.Start();
        File.WriteAllText(Path.Combine(data, "server.pid"), server.Id.ToString(), Encoding.ASCII);
        server.BeginOutputReadLine();
        server.BeginErrorReadLine();
        Add("\u5df2\u542f\u52a8\u540e\u53f0\u670d\u52a1\uff0cPID=" + server.Id);
    }

    private void AppendServer(string name, string line)
    {
        try { File.AppendAllText(Path.Combine(data, "logs", name), line + Environment.NewLine, Encoding.UTF8); }
        catch { }
    }
}
