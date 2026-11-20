// EstudioGTA6.exe — abre o Estúdio sem janela preta.
// Compilado no Windows pelo montar_exe (csc do .NET Framework que já vem no Windows).
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Lancador
{
    [STAThread]
    static void Main(string[] args)
    {
        string app = AppDomain.CurrentDomain.BaseDirectory;
        string py = Path.Combine(app, "runtime", "python.exe");
        string iniciar = Path.Combine(app, "iniciar.py");
        if (!File.Exists(py) || !File.Exists(iniciar))
        {
            MessageBox.Show("Arquivos do programa não encontrados em:\n" + app + "\n\nReinstale o Estúdio GTA 6.",
                            "Estúdio GTA 6", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        var psi = new ProcessStartInfo(py, "\"" + iniciar + "\"");
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;                 // console escondido: ffmpeg e scripts filhos também não piscam
        psi.WorkingDirectory = app;
        psi.EnvironmentVariables.Remove("PYTHONHOME");
        psi.EnvironmentVariables.Remove("PYTHONPATH");
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
        psi.EnvironmentVariables["PATH"] = Path.Combine(app, "bin") + ";" + Path.Combine(app, "runtime") + ";" +
                                           Path.Combine(app, "runtime", "Scripts") + ";" + psi.EnvironmentVariables["PATH"];
        try { Process.Start(psi); }
        catch (Exception e)
        {
            MessageBox.Show("Não consegui abrir o Estúdio:\n" + e.Message, "Estúdio GTA 6",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
