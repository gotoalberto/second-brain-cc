#!/usr/bin/env perl
# kp_kdbx.pl: a direct File::KDBX binding for the operations kp_backend.py's kpcli
# backend translates: ls, search, show, mkdir, add, edit, mv, rm, rmdir.
#
# WHY THIS EXISTS. `kp.py` speaks one protocol, keepassxc-cli's. A machine sharing a `.kdbx`
# over a synced path (never S3 — see brain_shared.py) may not have KeePassXC installed, but
# may have Perl and the `kpcli` package's underlying module, File::KDBX. The real `kpcli` tool
# itself is an interactive shell with no scriptable non-interactive mode worth the name, so it
# is never invoked here: this script reads and writes the KDBX file directly instead, through
# File::KDBX, and kp_backend.py runs THIS script (never a system "kpcli" binary) for the kpcli
# backend. See kp_backend.py's module docstring for the full routing story, and
# 30-Knowledge/... in the vault for the "does not fit in a public-repo pack" background.
#
# INVOCATION (built by kp_backend.py's translate()+build(), never typed by hand):
#   kp_kdbx.pl <op> [op-specific flags] --db PATH --pwfile PATH
#
#     ls      [--recursive] [--flatten] [--group GROUP]
#     search  --text TEXT
#     show    --entry ENTRY [--attr ATTR] [--reveal]
#     mkdir   --group GROUP
#     add     --entry ENTRY [--user U] [--url U] [--notes N] [--stdin-secret] [--generate [--length N]]
#     edit    --entry ENTRY [--title T] [--user U] [--url U] [--notes N] [--stdin-secret] [--generate [--length N]]
#     mv      --entry ENTRY --group GROUP
#     rm      --entry ENTRY
#     rmdir   --group GROUP
#
# The master password is read from --pwfile (a private 0600 temp file kp_backend.py writes
# and shreds: never argv, never the environment). A key FILE, when the store has one, is
# named by BRAIN_KP_KEYFILE in the environment: it is a path, not a secret. The key is then
# the master and the key file together, or the key file alone when the password file is
# empty. An empty password next to a key file is NOT the key file alone: File::KDBX treats
# "" as a real password and the composite fails the header check, so it is dropped. --stdin-secret means: read a NEW secret
# from stdin. kp_backend.py's split_confirmation() has ALREADY collapsed kp.py's
# `given\ngiven\n` double-write onto stdin before this runs — this script reads stdin as one
# value, nothing more, and must never re-implement that fix itself.
#
# Output: `ls`/`search` print one path per line, closest in spirit to keepassxc-cli -f; `show`
# prints "field: value" lines, `--attr` limited to just that field's value on its own line
# (masked as **** unless --reveal). Exit 0 on success; a message on stderr and a non-zero exit
# otherwise — kp_backend.run()'s subprocess.run() reads this the same way it reads
# keepassxc-cli's own exit codes.
#
# DEPENDENCY. File::KDBX is NOT in the Perl core; install it with:
#     cpanm --local-lib=~/perl5 File::KDBX
# `PERL5LIB` (or `-I`) comes from BRAIN_KP_PERL5LIB when set, else the standard
# --local-lib location, ~/perl5/lib/perl5 — generic, not a private path: it is cpanm's own
# convention, not anything machine-specific. See kp_kdbx_pl_test.py for how this is verified
# without requiring Perl or File::KDBX to be installed everywhere run_all_tests.py runs.

use strict;
use warnings;
use Getopt::Long qw(GetOptions);

BEGIN {
    my $extra = $ENV{BRAIN_KP_PERL5LIB};
    if (!defined($extra) || $extra eq '') {
        $extra = ($ENV{HOME} || '') . '/perl5/lib/perl5';
    }
    # `lib` rather than a bare unshift: it also adds the architecture directory, where
    # cpanm puts the compiled modules File::KDBX needs (CryptX and friends).
    if (-d $extra) { require lib; lib->import($extra); }
}

my $HAVE_KDBX = eval { require File::KDBX; File::KDBX->import; 1 };

sub fail {
    my ($msg) = @_;
    print STDERR "kp_kdbx: $msg\n";
    exit 1;
}

# File::KDBX ships no password generator of its own (confirmed by grepping the whole
# installed distribution — Util.pm, Entry.pm, Group.pm, KDBX.pm — nothing there). This
# generates one locally instead of adding a CPAN dependency for it. The character set
# mirrors kp.py's own keepassxc-cli generate call (`-g -L n -l -U -n -s`: lower, upper,
# digits, special) so a kpcli-generated password looks like the same class of password
# as a keepassxc-cli-generated one. Randomness comes from /dev/urandom, not Perl's
# built-in rand(), which is not seeded securely enough for this.
sub generate_password {
    my (%args) = @_;
    my $len = $args{length} || 24;
    my @chars = ('a' .. 'z', 'A' .. 'Z', '0' .. '9', split //, '!@#$%^&*-_=+?');
    open(my $fh, '<:raw', '/dev/urandom') or fail("cannot read /dev/urandom: $!");
    my $raw;
    read($fh, $raw, $len) == $len or fail("short read from /dev/urandom");
    close($fh);
    my $pw = '';
    $pw .= $chars[ord(substr($raw, $_, 1)) % scalar(@chars)] for 0 .. $len - 1;
    return $pw;
}

fail("File::KDBX is not installed. Install it with:\n" .
     "    cpanm --local-lib=~/perl5 File::KDBX\n" .
     "(see the README's \"Multiple machines\" section)") unless $HAVE_KDBX;

my $op = shift @ARGV;
fail("no operation given") unless defined($op) && length($op);

my (%opt, $recursive, $flatten, $group, $text, $entry, $attr, $reveal, $new_title,
    $user, $url, $notes, $stdin_secret, $generate, $length, $db, $pwfile);
GetOptions(
    'recursive'    => \$recursive,
    'flatten'      => \$flatten,
    'group=s'      => \$group,
    'text=s'       => \$text,
    'entry=s'      => \$entry,
    'attr=s'       => \$attr,
    'reveal'       => \$reveal,
    'title=s'      => \$new_title,
    'user=s'       => \$user,
    'url=s'        => \$url,
    'notes=s'      => \$notes,
    'stdin-secret' => \$stdin_secret,
    'generate'     => \$generate,
    'length=i'     => \$length,
    'db=s'         => \$db,
    'pwfile=s'     => \$pwfile,
) or fail("could not parse arguments");

fail("--db is required") unless defined($db) && length($db);
fail("--pwfile is required") unless defined($pwfile) && length($pwfile);
fail("the database does not exist: $db") unless -e $db;

my $master = do {
    open(my $fh, '<', $pwfile) or fail("cannot read the master from $pwfile: $!");
    local $/;
    my $pw = <$fh>;
    close($fh);
    $pw = '' unless defined($pw);
    $pw =~ s/\n\z//;
    $pw;
};
my $keyfile = $ENV{BRAIN_KP_KEYFILE};
$keyfile = '' unless defined($keyfile);
fail("empty master password and no key file") unless length($master) || length($keyfile);

# File::KDBX takes a bare string (password only), a Key::File (key file only) or an
# arrayref of both. The same $key opens the store and saves it back.
my $key = $master;
if (length($keyfile)) {
    fail("the key file does not exist: $keyfile") unless -e $keyfile;
    eval { require File::KDBX::Key::File; 1 }
        or fail("File::KDBX::Key::File is not installed; it ships with File::KDBX");
    my $kf = File::KDBX::Key::File->new($keyfile);
    $key = length($master) ? [$master, $kf] : $kf;
}

my $kdbx = eval { File::KDBX->load_file($db, $key) };
if (!$kdbx) {
    my $err = $@ || 'unknown error';
    # Phrased to include "wrong key": kp.py's own _BAD_KEY pattern
    # (invalid credentials|wrong key|could not be decrypted) is what tells a bad password
    # apart from every other failure, on both the initial probe in unlocked() and cli()'s own
    # kpcli branch. Wording this differently would make a wrong master look like any other
    # error and skip the "wrong master password" message the user actually needs.
    fail("cannot open the database: wrong key, or not a KDBX file ($err)");
}

sub group_path {
    my ($g) = @_;
    return join('/', map { $_->name } $g->lineage, $g) if $g->parent;
    return $g->name;
}

sub find_group {
    my ($path, $create) = @_;
    my $root = $kdbx->root;
    return $root unless defined($path) && length($path);
    my @parts = grep { length($_) } split(m{/}, $path);
    my $cur = $root;
    for my $part (@parts) {
        my ($next) = grep { $_->name eq $part } @{$cur->groups};
        if (!$next) {
            fail("no such group: $path") unless $create;
            $next = $cur->add_group(name => $part);
        }
        $cur = $next;
    }
    return $cur;
}

sub find_entry {
    my ($path) = @_;
    my @parts = grep { length($_) } split(m{/}, $path);
    fail("not an entry path: $path") unless @parts;
    my $title = pop @parts;
    my $group = find_group(join('/', @parts), 0);
    my ($e) = grep { ($_->title // '') eq $title } @{$group->entries};
    return $e;
}

if ($op eq 'ls') {
    my $start = find_group($group, 0);
    my @rows;
    my $walk;
    $walk = sub {
        my ($g, $prefix) = @_;
        for my $e (@{$g->entries}) {
            push @rows, ($prefix eq '' ? $e->title : "$prefix/" . $e->title);
        }
        return unless $recursive;
        for my $sub (@{$g->groups}) {
            my $next_prefix = $prefix eq '' ? $sub->name : "$prefix/" . $sub->name;
            $walk->($sub, $next_prefix);
        }
    };
    $walk->($start, '');
    print "$_\n" for sort @rows;
    exit 0;
}

if ($op eq 'search') {
    fail("--text is required") unless defined($text) && length($text);
    my @hits;
    my $walk;
    $walk = sub {
        my ($g, $prefix) = @_;
        for my $e (@{$g->entries}) {
            my $path = $prefix eq '' ? $e->title : "$prefix/" . $e->title;
            push @hits, $path if index(lc($path), lc($text)) >= 0;
        }
        for my $sub (@{$g->groups}) {
            my $next_prefix = $prefix eq '' ? $sub->name : "$prefix/" . $sub->name;
            $walk->($sub, $next_prefix);
        }
    };
    $walk->($kdbx->root, '');
    print "$_\n" for sort @hits;
    exit 0;
}

if ($op eq 'show') {
    fail("--entry is required") unless defined($entry) && length($entry);
    my $e = find_entry($entry);
    fail("no such entry: $entry") unless $e;
    if (defined($attr)) {
        # Password is a protected field in KeePass's data model: File::KDBX keeps its real
        # value out of the plain string storage that ->string_value (and ->password, which
        # is only a thin wrapper around ->string_value) reads, so both come back undef for
        # a database that was just loaded from disk. ->string_peek is what actually reaches
        # into protected memory and decrypts it — the same call the plain "show" (no
        # --attr) branch below already relies on for its own Password line.
        my $is_secret = (lc($attr) eq 'password');
        my $value = $is_secret ? $e->string_peek('Password') : $e->string_value($attr);
        $value = '' unless defined($value);
        print(($reveal || !$is_secret) ? $value : ($value eq '' ? '' : '****'), "\n");
        exit 0;
    }
    for my $field (qw(Title UserName URL Notes)) {
        my $value = $e->string_value($field);
        print "$field: ", (defined($value) ? $value : ''), "\n";
    }
    print "Password: ", ($reveal ? ($e->string_peek('Password') // '') : '****'), "\n";
    exit 0;
}

if ($op eq 'mkdir') {
    fail("--group is required") unless defined($group) && length($group);
    find_group($group, 1);
    $kdbx->dump_file($db, $key);
    exit 0;
}

if ($op eq 'add' || $op eq 'edit') {
    fail("--entry is required") unless defined($entry) && length($entry);
    my @parts = grep { length($_) } split(m{/}, $entry);
    fail("not an entry path: $entry") unless @parts;
    my $title = pop @parts;
    my $group_p = join('/', @parts);

    my $e = find_entry($entry);
    if ($op eq 'add') {
        fail("already exists: $entry") if $e;
        my $g = find_group($group_p, 1);
        $e = $g->add_entry(title => $title);
    } else {
        fail("no such entry: $entry") unless $e;
    }

    $e->title($new_title) if defined($new_title) && length($new_title);
    $e->username($user) if defined($user);
    $e->url($url) if defined($url);
    $e->notes($notes) if defined($notes);

    if ($stdin_secret) {
        local $/;
        my $secret = <STDIN>;
        $secret = '' unless defined($secret);
        $secret =~ s/\n\z//;
        $e->password($secret);
    } elsif ($generate) {
        my $len = (defined($length) && $length > 0) ? $length : 24;
        $e->password(generate_password(length => $len));
    } elsif ($op eq 'add') {
        my $len = (defined($length) && $length > 0) ? $length : 24;
        $e->password(generate_password(length => $len));
    }

    $kdbx->dump_file($db, $key);
    print(($op eq 'add' ? 'created' : 'updated'), ": $entry\n");
    exit 0;
}

# Every save below uses $key, the exact key the store was opened with, never $master alone:
# on a keyfile-only store $master is "", and saving with it would re-key the whole store
# under an EMPTY password and no key file.

# `mv` relocates only, the same shape keepassxc-cli uses. kp.py's cmd_mv renames with a
# follow-up `edit --title`, so this never has to.
if ($op eq 'mv') {
    fail("--entry is required") unless defined($entry) && length($entry);
    fail("--group is required") unless defined($group);
    my $e = find_entry($entry);
    fail("no such entry: $entry") unless $e;
    my $dst = find_group($group, 1);
    $e->remove;
    $dst->add_entry($e);
    $kdbx->dump_file($db, $key);
    print "moved: $entry\n";
    exit 0;
}

# `rm` detaches the entry from its group. The recycle bin is NOT used: a half-hidden second
# copy makes "is it gone?" unanswerable. kp.py takes a backup before calling and verifies
# (or restores) afterwards, so a delete is recoverable there.
if ($op eq 'rm') {
    fail("--entry is required") unless defined($entry) && length($entry);
    my $e = find_entry($entry);
    fail("no such entry: $entry") unless $e;
    $e->remove;
    $kdbx->dump_file($db, $key);
    print "deleted: $entry\n";
    exit 0;
}

# `rmdir` only ever removes an empty group, and never the root. kp.py checks emptiness
# before calling and this checks again: on a store shared between machines the two checks
# can be minutes apart.
if ($op eq 'rmdir') {
    fail("--group is required") unless defined($group) && length($group);
    my $g = find_group($group, 0);
    fail("the root group is never removed") if $g == $kdbx->root;
    fail("the group is not empty: $group") if @{$g->entries} || @{$g->groups};
    $g->remove;
    $kdbx->dump_file($db, $key);
    exit 0;
}

fail("unsupported operation: $op");
