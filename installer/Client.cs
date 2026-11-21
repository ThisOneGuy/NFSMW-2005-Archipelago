using System;
using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Windows.Forms;

[assembly:AssemblyTitle("NFSMW Client")]
[assembly:AssemblyDescription("Archipelago connection for Need for Speed Most Wanted")]
[assembly:AssemblyCompany("NFSMW Archipelago")]
[assembly:AssemblyProduct("NFSMW Archipelago Client")]
[assembly:AssemblyVersion("1.0.6.0")]
[assembly:AssemblyFileVersion("1.0.6.0")]
[assembly:System.Runtime.Versioning.TargetFramework(
    ".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]

internal static class Client
{
    internal static string QuoteArgument(string value)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\')
            {
                slashes++;
                continue;
            }
            if (c == '"')
                result.Append('\\', slashes * 2 + 1).Append(c);
            else
                result.Append('\\', slashes).Append(c);
            slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }

    internal static string FolderPrefix(string value)
    {
        return value.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) +
            Path.DirectorySeparatorChar;
    }

    internal static string FolderPath(string value)
    {
        if (String.IsNullOrWhiteSpace(value))
            throw new IOException("Choose the game folder containing speed.exe.");
        value = value.Trim();
        if (value.Length >= 2 && value[0] == '"' && value[value.Length - 1] == '"')
            value = value.Substring(1, value.Length - 2);
        string folder = Path.GetFullPath(value), drive = Path.GetPathRoot(Path.GetFullPath(value));
        while (folder.Length > drive.Length &&
            (folder[folder.Length - 1] == Path.DirectorySeparatorChar ||
                folder[folder.Length - 1] == Path.AltDirectorySeparatorChar))
            folder = folder.Substring(0, folder.Length - 1);
        if (File.Exists(folder))
        {
            if (!String.Equals(
                    Path.GetFileName(folder), "speed.exe", StringComparison.OrdinalIgnoreCase))
                throw new IOException("Choose the game folder or speed.exe.");
            folder = Path.GetDirectoryName(folder);
        }
        return folder;
    }

    static bool Pe32(string file)
    {
        if (!File.Exists(file))
            return false;
        using (var stream = File.OpenRead(file)) using (var reader = new BinaryReader(stream))
        {
            if (stream.Length < 64 || reader.ReadUInt16() != 0x5a4d)
                return false;
            stream.Position = 60;
            int offset = reader.ReadInt32();
            if (offset < 64 || offset > stream.Length - 6)
                return false;
            stream.Position = offset;
            return reader.ReadUInt32() == 0x4550 && reader.ReadUInt16() == 0x14c;
        }
    }

    internal static bool NormalFolder(string folder)
    {
        return !Directory.Exists(folder) ||
            (File.GetAttributes(folder) & FileAttributes.ReparsePoint) == 0;
    }

    internal static bool CheckGame(string folder)
    {
        folder = FolderPath(folder);
        string game = Path.Combine(folder, "speed.exe");
        return Directory.Exists(folder) && NormalFolder(folder) && Pe32(game) &&
            (File.GetAttributes(game) & FileAttributes.ReparsePoint) == 0 &&
            NormalFolder(Path.Combine(folder, "scripts")) &&
            NormalFolder(Path.Combine(folder, "NFSMWClient_Data"));
    }

    internal static string Hash(string file)
    {
        using (var sha = SHA256.Create()) using (
            var stream = File.OpenRead(file)) return BitConverter.ToString(sha.ComputeHash(stream))
            .Replace("-", "")
            .ToLowerInvariant();
    }

    internal static void VerifyFiles(string root)
    {
        root = FolderPath(root);
        string data = Path.GetFullPath(Path.Combine(root, "NFSMWClient_Data"));
        if (!NormalFolder(data))
            throw new IOException("The client data folder must be a normal folder.");
        bool boot = false, python = false, app = false;
        foreach (string line in File.ReadAllLines(Path.Combine(data, "launcher_files.sha256")))
        {
            if (line.Length < 67 || line[64] != ' ' || line[65] != '*')
                throw new IOException("Invalid client file list.");
            string name = line.Substring(66);
            if (Path.IsPathRooted(name) || name.Contains("..") || name.Contains(":"))
                throw new IOException("Invalid client file path.");
            string file = Path.GetFullPath(
                Path.Combine(data, name.Replace('/', Path.DirectorySeparatorChar)));
            if (!file.StartsWith(
                    data + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                throw new IOException("Invalid client file path.");
            for (var parent = new DirectoryInfo(Path.GetDirectoryName(file));
                parent != null && parent.FullName.Length >= data.Length; parent = parent.Parent)
                if (parent.Exists && (parent.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Linked client data folders are not supported.");
            if (!File.Exists(file) ||
                (File.GetAttributes(file) & FileAttributes.ReparsePoint) != 0 ||
                Hash(file) != line.Substring(0, 64))
                throw new IOException("A client file is missing or damaged: " + name +
                    ". Run NFSMW Setup to repair it.");
            boot |= name == "boot.pyw";
            python |= name == "runtime/pythonw.exe";
            app |= name == "app.zip";
        }
        if (!boot || !python || !app)
            throw new IOException(
                "The client file list is incomplete. Run NFSMW Setup to repair it.");
    }

    internal static ProcessStartInfo StartInfo(string root)
    {
        root = FolderPath(root);
        var info =
            new ProcessStartInfo(Path.Combine(root, "NFSMWClient_Data", "runtime", "pythonw.exe"));
        info.Arguments =
            "-I -S -B " + QuoteArgument(Path.Combine(root, "NFSMWClient_Data", "boot.pyw"));
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        return info;
    }

    [STAThread]
    static int Main()
    {
        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            if (!CheckGame(root))
                throw new IOException(
                    "Place the complete manual package beside speed.exe, or use NFSMW Setup.");
            VerifyFiles(root);
            Process.Start(StartInfo(root));
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show(
                error.Message, "NFSMW Client", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
